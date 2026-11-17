"""阿里云函数计算：共享数据的写入口（HTTP 函数，WSGI 形式）。

职责只有四件事，都很便宜：

1. **鉴权**：共享 token 校验（客户端只带这一个口令，永远拿不到 OSS 密钥）
2. **校验**：商人/货物白名单、价格区间、字段类型、体积上限
3. **限流**：同一个商人 3 秒内只接受一次写（价格不可能变这么快）
4. **写库**：读-合并-条件写商人对象，然后更新 index.json（客户端只读它）

环境变量（在函数计算的"配置 → 环境变量"里设置）：

    OSS_ENDPOINT        https://oss-cn-hangzhou.aliyuncs.com
    OSS_BUCKET          <你的桶名>
    OSS_KEY_ID          <RAM 用户 AccessKeyId>
    OSS_KEY_SECRET      <RAM 用户 AccessKeySecret>
    SHARE_TOKEN         <共享口令>

RAM 用户的权限只需要：oss:GetObject / oss:PutObject，资源限定在
``acs:oss:*:*:<bucket>/merchants/*`` 和 ``.../index.json``。
"""

import json
import time

import oss2

import os

PREFIX = "merchants/"
INDEX_KEY = "index.json"
MAX_BODY = 2048
MAX_ROWS = 12
MAX_REFRESH = 360
MIN_WRITE_INTERVAL = 3.0

#: 允许的商人 id（留空表示不限制，但格式仍然校验）
ALLOWED_MERCHANTS = set()

_bucket = None


def bucket():
    global _bucket
    if _bucket is None:
        auth = oss2.Auth(os.environ["OSS_KEY_ID"], os.environ["OSS_KEY_SECRET"])
        _bucket = oss2.Bucket(auth, os.environ["OSS_ENDPOINT"], os.environ["OSS_BUCKET"])
    return _bucket


def _json_response(start_response, status, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    start_response(status, [("Content-Type", "application/json; charset=utf-8"),
                            ("Content-Length", str(len(body)))])
    return [body]


def _merchant_id_valid(merchant_id):
    if not isinstance(merchant_id, str) or not merchant_id:
        return False
    if len(merchant_id) > 32:
        return False
    if not all(ch.isalnum() or ch in "_-" for ch in merchant_id):
        return False
    return not ALLOWED_MERCHANTS or merchant_id in ALLOWED_MERCHANTS


def validate_record(record, merchant_id, now):
    """校验客户端提交的记录；返回 (清洗后的记录, 错误信息)。"""
    if not isinstance(record, dict):
        return None, "record 不是对象"
    rows = record.get("rows")
    if not isinstance(rows, dict) or not rows:
        return None, "rows 为空"
    if len(rows) > MAX_ROWS:
        return None, "rows 太多"
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
        # 服务器时间兜底：不接受未来时间（防时钟漂移/恶意钉住）
        t = min(t, now)
        clean[key] = {"p": price, "t": t, "r": r}
    return {"v": 1, "merchant_id": merchant_id,
            "map": str(record.get("map") or "")[:32],
            "writer": str(record.get("writer") or "")[:32],
            "rev": int(record.get("rev") or 0), "rows": clean}, ""


def read_object(merchant_id):
    try:
        result = bucket().get_object(f"{PREFIX}{merchant_id}.json")
        return json.loads(result.read().decode("utf-8")), result.headers.get("ETag")
    except oss2.exceptions.NoSuchKey:
        return None, None
    except Exception:
        return None, None


def newest_t(record):
    if not record:
        return 0.0
    return max((float(r.get("t", 0)) for r in (record.get("rows") or {}).values()),
               default=0.0)


def update_index(merchant_id, etag):
    """index.json：{merchant_id: etag}，客户端只读它就知道该下哪些。"""
    try:
        result = bucket().get_object(INDEX_KEY)
        index = json.loads(result.read().decode("utf-8")) or {}
        current_etag = result.headers.get("ETag")
    except Exception:
        index, current_etag = {}, None
    index[merchant_id] = etag
    body = json.dumps(index, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if current_etag:
        headers["If-Match"] = current_etag
    try:
        bucket().put_object(INDEX_KEY, body, headers=headers)
    except Exception:
        # index 写失败不影响商人对象本身；下次写会重建
        pass


def handle_upload(payload, now):
    token = os.environ.get("SHARE_TOKEN", "")
    if not token or payload.get("token") != token:
        return 401, {"ok": False, "error": "token 不对"}
    merchant_id = payload.get("merchant_id")
    if not _merchant_id_valid(merchant_id):
        return 400, {"ok": False, "error": "商人 id 不合法"}
    record, error = validate_record(payload.get("record"), merchant_id, now)
    if error:
        return 400, {"ok": False, "error": error}

    existing, etag = read_object(merchant_id)
    if existing and now - newest_t(existing) < MIN_WRITE_INTERVAL:
        return 429, {"ok": False, "error": "写太快，同一个商人 3 秒内只收一次"}

    body = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_BODY:
        return 413, {"ok": False, "error": "记录太大"}

    headers = {"Content-Type": "application/json"}
    if etag:
        headers["If-Match"] = etag
    try:
        result = bucket().put_object(f"{PREFIX}{merchant_id}.json", body, headers=headers)
    except Exception as exc:
        return 409, {"ok": False, "error": f"冲突：{exc}"}
    new_etag = result.headers.get("ETag", "")
    update_index(merchant_id, new_etag)
    return 200, {"ok": True, "etag": new_etag}


def handler(environ, start_response):
    """FC 的 HTTP 函数入口（WSGI）。"""
    now = time.time()
    try:
        if environ.get("REQUEST_METHOD") != "POST":
            return _json_response(start_response, "405 Method Not Allowed",
                                  {"ok": False, "error": "只接受 POST"})
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY * 2:
            return _json_response(start_response, "413 Payload Too Large",
                                  {"ok": False, "error": "请求太大"})
        raw = environ["wsgi.input"].read(length) if length else b""
        payload = json.loads(raw.decode("utf-8"))
        status, body = handle_upload(payload, now)
        return _json_response(start_response, f"{status} OK", body)
    except Exception as exc:
        return _json_response(start_response, "500 Internal Server Error",
                              {"ok": False, "error": str(exc)[:120]})
