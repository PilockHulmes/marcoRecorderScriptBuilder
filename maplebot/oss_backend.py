"""OSS 后端：读走公共前缀，写走中转函数（本地开发可直连）。

两种模式：

**生产（默认）**：客户端只有 ``share.json`` 里的 token，没有任何 OSS 密钥。
    读：GET ``<read_prefix>index.json`` 拿 {商人: etag}，再按需 GET ``<read_prefix><商人>.json``
    写：POST ``<upload_url>``（函数计算），带 token

**开发**：环境变量里有 ``OSS_ACCESS_KEY_ID`` / ``OSS_ACCESS_KEY_SECRET`` 时直连 OSS，
方便本机调试；分发给别人时不需要。

对象布局：``merchants/<merchant_id>.json``，一个商人一个对象；
``index.json`` 记录每个商人当前的 etag（函数写完会更新它）。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import share_config

PREFIX = "merchants/"
INDEX_KEY = "index.json"


def _key(merchant_id):
    return f"{PREFIX}{merchant_id}.json"


def _merchant_of(key):
    if not key.startswith(PREFIX) or not key.endswith(".json"):
        return ""
    return key[len(PREFIX):-len(".json")]


class OssBackend:
    def __init__(self, config=None, auth=None):
        self.config = config or share_config.load_config()
        self.endpoint = self.config.get("endpoint", "")
        self.bucket_name = self.config.get("bucket", "")
        self.token = self.config.get("token", "")
        self.upload_url = self.config.get("upload_url", "")
        self.read_prefix = self.config.get("read_prefix", "")
        self._bucket = None
        self._auth = auth

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
    def list_objects(self):
        """读 index.json（一个请求）；没有就退回 OSS list。"""
        if self.direct:
            bucket = self.bucket()
            out = {}
            for info in bucket.list_objects(prefix=PREFIX, max_keys=1000).object_list:
                merchant_id = _merchant_of(info.key)
                if merchant_id:
                    out[merchant_id] = info.etag
            return out
        index = self._get_public(INDEX_KEY)
        if isinstance(index, dict):
            return {str(k): str(v) for k, v in index.items()}
        return {}

    def get(self, merchant_id):
        if self.direct:
            bucket = self.bucket()
            try:
                result = bucket.get_object(_key(merchant_id))
            except Exception as exc:
                if "NoSuchKey" in str(exc) or "404" in str(exc):
                    return None, None
                raise IOError(str(exc)) from exc
            payload = result.read()
            etag = result.headers.get("ETag") or result.headers.get("etag")
            return self._parse(payload), etag
        payload = self._get_public(_key(merchant_id))
        if payload is None:
            return None, None
        return payload, None          # 用 index 里的 etag，这里不再取

    def _get_public(self, key):
        if not self.read_prefix:
            raise IOError("没有配置 read_prefix")
        url = self.read_prefix.rstrip("/") + "/" + key
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return self._parse(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 403):
                return None
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
            raise IOError("没有配置 upload_url（写请求必须走中转）")
        body = json.dumps({"token": self.token, "merchant_id": merchant_id,
                           "record": record}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.upload_url, data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
                return bool(payload.get("ok"))
        except urllib.error.HTTPError as exc:
            if exc.code in (409, 412):
                return False
            if exc.code == 429:
                raise IOError("429") from exc
            raise IOError(f"上传失败：{exc.code}") from exc
        except Exception as exc:
            raise IOError(str(exc)) from exc

    def _put_direct(self, merchant_id, record, etag):
        bucket = self.bucket()
        body = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if etag:
            headers["If-Match"] = etag
        else:
            headers["If-None-Match"] = "*"
        try:
            bucket.put_object(_key(merchant_id), body, headers=headers)
            return True
        except Exception as exc:
            text = str(exc)
            if "PreconditionFailed" in text or "412" in text:
                return False
            raise IOError(text) from exc
