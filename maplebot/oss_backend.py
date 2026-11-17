"""OSS 后端：读走预签名 URL（直连 OSS），写走中转函数。

为什么不是"公共读"：实测这个 RAM 用户没有 ``PutObjectAcl`` 权限，对象设不了公开；
但**预签名 URL 可用**。所以：

    每 ~5 分钟向函数要一次 bundle：{index_url, 每个商人的预签名 url + etag}
    之后 1 秒一次的轮询直接 GET 这些 URL（不经过函数，不消耗函数额度）

为什么冲突检测在函数里：实测 OSS 的 PutObject **不支持 If-Match**（返回
NotImplemented），所以客户端把上次看到的 etag 一起提交，函数比对后决定
是否 409。冲突窗口只有一次读写的时间（毫秒级），且 merge 逻辑能兜住。

开发机（环境变量里有 AccessKey）则直连 OSS，方便本机调试。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from . import share_config

PREFIX = "merchants/"
INDEX_KEY = "index.json"

#: bundle 提前多少秒视为过期（留出网络余量）
BUNDLE_MARGIN = 30.0


def _key(merchant_id):
    return f"{PREFIX}{merchant_id}.json"


def _merchant_of(key):
    if not key.startswith(PREFIX) or not key.endswith(".json"):
        return ""
    return key[len(PREFIX):-len(".json")]


class OssBackend:
    def __init__(self, config=None, auth=None, now=time.time):
        self.config = config or share_config.load_config()
        self.endpoint = self.config.get("endpoint", "")
        self.bucket_name = self.config.get("bucket", "")
        self.token = self.config.get("token", "")
        self.upload_url = self.config.get("upload_url", "")
        self.bundle_url = self.config.get("bundle_url", "")
        if not self.bundle_url and self.upload_url:
            self.bundle_url = self.upload_url.replace("/upload", "/bundle")
        self.now = now
        self._bucket = None
        self._auth = auth
        self._bundle = None          # {"index_url": ..., "objects": {...}, "expires": ...}
        self._bundle_at = 0.0

    # ------------------------------------------------------------------ 直连
    def bucket(self):
        if self._bucket is not None:
            return self._bucket
        import oss2
        if self._auth is None:
            key_id, secret = share_config.dev_credentials()
            if not key_id:
                raise RuntimeError("没有 OSS 凭证（生产模式应走中转）")
            self._auth = oss2.Auth(key_id, secret)
        self._bucket = oss2.Bucket(self._auth, self.endpoint, self.bucket_name)
        return self._bucket

    @property
    def direct(self):
        key_id, _secret = share_config.dev_credentials()
        return bool(key_id) or self._auth is not None

    # ------------------------------------------------------------------ 读
    def bundle(self):
        """拿/复用预签名 URL 包（约 5 分钟有效）。"""
        moment = self.now()
        if self._bundle and moment < self._bundle.get("expires", 0) - BUNDLE_MARGIN:
            return self._bundle
        if not self.bundle_url:
            raise IOError("没有配置 bundle_url")
        payload = self._post(self.bundle_url, {"token": self.token})
        if not payload.get("ok"):
            raise IOError(payload.get("error") or "bundle 失败")
        self._bundle = payload
        self._bundle_at = moment
        return payload

    def list_objects(self):
        if self.direct:
            bucket = self.bucket()
            out = {}
            for info in bucket.list_objects(prefix=PREFIX, max_keys=1000).object_list:
                merchant_id = _merchant_of(info.key)
                if merchant_id:
                    out[merchant_id] = info.etag
            return out
        bundle = self.bundle()
        index_url = bundle.get("index_url")
        if index_url:
            try:
                index = self._fetch(index_url)
                if isinstance(index, dict):
                    return {str(k): str(v) for k, v in index.items()}
            except IOError:
                pass                       # 预签名过期/none：退回 bundle 里的 etag
        return {mid: info.get("etag", "")
                for mid, info in (bundle.get("objects") or {}).items()}

    def get(self, merchant_id):
        if self.direct:
            bucket = self.bucket()
            try:
                result = bucket.get_object(_key(merchant_id))
            except Exception as exc:
                if "NoSuchKey" in str(exc) or "404" in str(exc):
                    return None, None
                raise IOError(str(exc)) from exc
            return self._parse(result.read()), result.headers.get("ETag")
        bundle = self.bundle()
        info = (bundle.get("objects") or {}).get(merchant_id)
        if not info or not info.get("url"):
            return None, None
        try:
            return self._fetch(info["url"]), info.get("etag")
        except IOError:
            self._bundle = None              # URL 过期：下次重新取 bundle
            raise

    @staticmethod
    def _opener():
        """不走系统/环境变量里的代理。

        实测：机器上配了代理但代理没开时，urllib 会报 10061「连接被拒绝」，
        而直连是通的（45~60 ms）。共享请求一律直连，避免被本地代理拖死。
        """
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _fetch(self, url):
        try:
            with self._opener().open(url, timeout=5) as response:
                return self._parse(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                raise IOError(f"HTTP {exc.code}") from exc
            raise IOError(str(exc)) from exc
        except Exception as exc:
            raise IOError(str(exc)) from exc

    @staticmethod
    def _parse(payload):
        try:
            return json.loads(payload.decode("utf-8") if isinstance(payload, bytes)
                              else payload)
        except Exception as exc:
            raise IOError(f"远端对象不是合法 JSON：{exc}") from exc

    # ------------------------------------------------------------------ 写
    def put_if_match(self, merchant_id, record, etag):
        if self.direct:
            return self._put_direct(merchant_id, record, etag)
        if not self.upload_url:
            raise IOError("没有配置 upload_url")
        payload = self._post(self.upload_url,
                             {"token": self.token, "merchant_id": merchant_id,
                              "record": record, "etag": etag or ""})
        return bool(payload.get("ok"))

    def _put_direct(self, merchant_id, record, etag):
        bucket = self.bucket()
        body = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            bucket.put_object(_key(merchant_id), body,
                              headers={"Content-Type": "application/json"})
            return True
        except Exception as exc:
            raise IOError(str(exc)) from exc

    def _post(self, url, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
        try:
            with self._opener().open(request, timeout=8) as response:
                return json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            if exc.code in (409, 412):
                return {"ok": False, "error": "conflict"}
            if exc.code == 429:
                raise IOError("429") from exc
            try:
                return json.loads(exc.read().decode("utf-8") or "{}")
            except Exception:
                raise IOError(f"HTTP {exc.code}") from exc
        except Exception as exc:
            raise IOError(str(exc)) from exc
