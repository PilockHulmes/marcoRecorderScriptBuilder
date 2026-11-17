"""阿里云函数计算：共享数据的读入口（预签名 URL）+ 写入口。

实测结论（照它们设计的）：

* 这个 RAM 用户不能把对象设成公共读 → 用**预签名 URL** 让别人读
* OSS 的 PutObject **不支持 If-Match** → 冲突检测放在这里
* oss2 没有 manylinux wheel → 换成只依赖标准库的 :mod:`ossmin`

    读：``/bundle`` 一次返回 index 和全部商人对象的预签名 URL（5 分钟有效）
        客户端拿 URL 直连 OSS，1 秒轮询也不消耗函数额度
    写：``/upload`` 校验 token / 字段 / 限流 / etag 冲突，然后写对象并更新 index

环境变量：``OSS_ENDPOINT`` ``OSS_BUCKET`` ``OSS_KEY_ID`` ``OSS_KEY_SECRET`` ``SHARE_TOKEN``
"""

import json
import os
import time

import ossmin

PREFIX = "merchants/"
INDEX_KEY = "index.json"
MAX_BODY = 2048
MAX_ROWS = 12
MAX_REFRESH = 360
MIN_WRITE_INTERVAL = 3.0
URL_TTL = 300


def _settings():
    return {
        "bucket": os.environ["OSS_BUCKET"],
        "endpoint": os.environ["OSS_ENDPOINT"],
        "access_id": os.environ["OSS_KEY_ID"],
        "secret": os.environ["OSS_KEY_SECRET"],
    }


def _get(key):
    s = _settings()
    body, etag = ossmin.get_object(s["bucket"], s["endpoint"], key,
                                   s["access_id"], s["secret"])
    if body is None:
        return None, None
    return json.loads(body.decode("utf-8")), etag


def _put(key, payload):
    s = _settings()
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return ossmin.put_object(s["bucket"], s["endpoint"], key, body,
                             s["access_id"], s["secret"])


def _presign(key):
    s = _settings()
    return ossmin.presign_get(s["bucket"], s["endpoint"], key,
                              s["access_id"], s["secret"], URL_TTL)


def _response(start_response, status, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    start_response(status, [("Content-Type", "application/json; charset=utf-8"),
                            ("Content-Length", str(len(body)))])
    return [body]


def _token_ok(payload):
    token = os.environ.get("SHARE_TOKEN", "")
    return bool(token) and payload.get("token") == token


def _valid_merchant(merchant_id):
    if not isinstance(merchant_id, str) or not merchant_id or len(merchant_id) > 32:
        return False
    return all(ch.isalnum() or ch in "_-" for ch in merchant_id)


def _newest_t(record):
    if not record:
        return 0.0
    return max((float(r.get("t", 0)) for r in (record.get("rows") or {}).values()),
               default=0.0)


def _validate_record(record, merchant_id, now):
    if not isinstance(record, dict):
        return None, "record 不是对象"
    rows = record.get("rows")
    if not isinstance(rows, dict) or not rows or len(rows) > MAX_ROWS:
        return None, "rows 不合法"
    clean = {}
    for key, row in rows.items():
        if not isinstance(key, str) or "|" not in key or len(key) > 64:
            return None, "行 key 不合法"
        good_id, _, side = key.partition("|")
        if not good_id or side not in ("buy", "sell") or not isinstance(row, dict):
            return None, "行不合法"
        try:
            price = int(row["p"])
            t = float(row["t"])
            r = float(row.get("r") or 0)
        except (KeyError, TypeError, ValueError):
            return None, "行字段不合法"
        if not (0 <= price <= 999999):
            return None, "价格越界"
        if not (0 <= r <= MAX_REFRESH):
            return None, "刷新时间越界"
        clean[key] = {"p": price, "t": min(t, now), "r": r}
    return {"v": 1, "merchant_id": merchant_id,
            "map": str(record.get("map") or "")[:32],
            "writer": str(record.get("writer") or "")[:32],
            "rev": int(record.get("rev") or 0), "rows": clean}, ""


def handle_bundle(payload):
    if not _token_ok(payload):
        return 401, {"ok": False, "error": "token 不对"}
    try:
        index, _etag = _get(INDEX_KEY)
    except Exception:
        index = {}
    index = index or {}
    objects = {}
    for merchant_id in list(index)[:64]:
        if not _valid_merchant(merchant_id):
            continue
        objects[merchant_id] = {
            "url": _presign(f"{PREFIX}{merchant_id}.json"),
            "etag": index.get(merchant_id, ""),
        }
    return 200, {"ok": True, "expires": int(time.time()) + URL_TTL,
                 "index_url": _presign(INDEX_KEY), "objects": objects}


def handle_upload(payload, now):
    if not _token_ok(payload):
        return 401, {"ok": False, "error": "token 不对"}
    merchant_id = payload.get("merchant_id")
    if not _valid_merchant(merchant_id):
        return 400, {"ok": False, "error": "商人 id 不合法"}
    record, error = _validate_record(payload.get("record"), merchant_id, now)
    if error:
        return 400, {"ok": False, "error": error}

    key = f"{PREFIX}{merchant_id}.json"
    existing, etag = _get(key)
    client_etag = payload.get("etag") or ""
    if existing and client_etag and client_etag != etag:
        return 409, {"ok": False, "error": "别人先写了，请合并后重试"}
    if existing and now - _newest_t(existing) < MIN_WRITE_INTERVAL:
        return 429, {"ok": False, "error": "同一个商人 3 秒内只收一次"}

    new_etag = _put(key, record)

    try:
        index, index_etag = _get(INDEX_KEY)
        index = index or {}
        index[merchant_id] = new_etag
        _put(INDEX_KEY, index)
    except Exception:
        pass
    return 200, {"ok": True, "etag": new_etag}


def handler(environ, start_response):
    """FC HTTP 函数入口：``/bundle`` 与 ``/upload``。"""
    now = time.time()
    path = (environ.get("PATH_INFO") or "/").rstrip("/") or "/"
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > MAX_BODY * 2:
        return _response(start_response, "413 Payload Too Large", {"ok": False})
    raw = environ["wsgi.input"].read(length) if length else b""
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except Exception:
        return _response(start_response, "400 Bad Request",
                         {"ok": False, "error": "不是 JSON"})
    try:
        if path.endswith("/bundle"):
            status, body = handle_bundle(payload)
        elif path.endswith("/upload"):
            status, body = handle_upload(payload, now)
        else:
            status, body = 404, {"ok": False, "error": "未知路径"}
        return _response(start_response, f"{status} OK", body)
    except Exception as exc:
        return _response(start_response, "500 Internal Server Error",
                         {"ok": False, "error": str(exc)[:120]})
