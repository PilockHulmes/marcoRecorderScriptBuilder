"""阿里云函数计算：共享数据的读入口（预签名 URL）+ 写入口。

实测结论：

* 这个 RAM 用户**不能**把对象设成公共读（``Put public object acl is not allowed``）
* 但**预签名 URL 可用**（匿名 GET 返回 200）
* OSS **不支持** ``If-Match`` 条件写（返回 ``NotImplemented``）

所以：

    读：``/bundle`` 一次性返回 index 和 15 个商人对象的预签名 URL（默认 5 分钟有效）
        客户端拿 URL 直连 OSS 轮询 → 1 秒一次也不消耗函数额度
    写：``/upload`` 校验 token / 字段 / 限流，并用"客户端带来的 etag 与当前对比"
        做冲突检测（OSS 不支持条件写，只能在这里串行化）

环境变量：

    OSS_ENDPOINT / OSS_BUCKET / OSS_KEY_ID / OSS_KEY_SECRET / SHARE_TOKEN
"""

import json
import os
import time

import oss2

PREFIX = "merchants/"
INDEX_KEY = "index.json"
MAX_BODY = 2048
MAX_ROWS = 12
MAX_REFRESH = 360
MIN_WRITE_INTERVAL = 3.0
URL_TTL = 300

_bucket = None


def bucket():
    global _bucket
    if _bucket is None:
        auth = oss2.Auth(os.environ["OSS_KEY_ID"], os.environ["OSS_KEY_SECRET"])
        _bucket = oss2.Bucket(auth, os.environ["OSS_ENDPOINT"], os.environ["OSS_BUCKET"])
    return _bucket


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


def _read_object(merchant_id):
    try:
        result = bucket().get_object(f"{PREFIX}{merchant_id}.json")
        return json.loads(result.read().decode("utf-8")), result.headers.get("ETag")
    except oss2.exceptions.NoSuchKey:
        return None, None
    except Exception:
        return None, None


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
        if not good_id or side not in ("buy", "sell"):
            return None, "行 key 不合法"
        if not isinstance(row, dict):
            return None, "行不是对象"
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
    """返回 index 和所有商人对象的预签名 URL。"""
    if not _token_ok(payload):
        return 401, {"ok": False, "error": "token 不对"}
    b = bucket()
    index = {}
    try:
        result = b.get_object(INDEX_KEY)
        index = json.loads(result.read().decode("utf-8")) or {}
    except Exception:
        index = {}
    objects = {}
    for merchant_id in index:
        if not _valid_merchant(merchant_id):
            continue
        key = f"{PREFIX}{merchant_id}.json"
        objects[merchant_id] = {
            "url": b.sign_url("GET", key, URL_TTL, slash_safe=True),
            "etag": index.get(merchant_id, ""),
        }
    return 200, {"ok": True, "expires": int(time.time()) + URL_TTL,
                 "index_url": b.sign_url("GET", INDEX_KEY, URL_TTL, slash_safe=True),
                 "objects": objects}


def handle_upload(payload, now):
    if not _token_ok(payload):
        return 401, {"ok": False, "error": "token 不对"}
    merchant_id = payload.get("merchant_id")
    if not _valid_merchant(merchant_id):
        return 400, {"ok": False, "error": "商人 id 不合法"}
    record, error = _validate_record(payload.get("record"), merchant_id, now)
    if error:
        return 400, {"ok": False, "error": error}

    existing, etag = _read_object(merchant_id)
    client_etag = payload.get("etag") or ""
    if existing and client_etag and client_etag != etag:
        return 409, {"ok": False, "error": "别人先写了，请合并后重试"}
    if existing and now - _newest_t(existing) < MIN_WRITE_INTERVAL:
        return 429, {"ok": False, "error": "同一个商人 3 秒内只收一次"}

    key = f"{PREFIX}{merchant_id}.json"
    body = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_BODY:
        return 413, {"ok": False, "error": "记录太大"}
    try:
        result = bucket().put_object(key, body,
                                     headers={"Content-Type": "application/json"})
    except Exception as exc:
        return 409, {"ok": False, "error": f"写入冲突：{exc}"}
    new_etag = result.headers.get("ETag", "")

    # index.json：客户端只读它就知道该下哪些（读-改-写，失败不影响对象本身）
    try:
        result = bucket().get_object(INDEX_KEY)
        index = json.loads(result.read().decode("utf-8")) or {}
        index_etag = result.headers.get("ETag")
    except Exception:
        index, index_etag = {}, None
    index[merchant_id] = new_etag
    headers = {"Content-Type": "application/json"}
    if index_etag:
        headers["If-Match"] = index_etag
    try:
        bucket().put_object(INDEX_KEY, json.dumps(index, ensure_ascii=False).encode("utf-8"),
                            headers=headers)
    except Exception:
        pass
    return 200, {"ok": True, "etag": new_etag}


def handler(environ, start_response):
    """FC HTTP 函数入口：``/bundle`` 和 ``/upload`` 两个路径。"""
    now = time.time()
    path = (environ.get("PATH_INFO") or "").rstrip("/") or "/"
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
        return _response(start_response, "400 Bad Request", {"ok": False, "error": "不是 JSON"})
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
