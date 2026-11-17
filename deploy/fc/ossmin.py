"""只用标准库的 OSS 客户端（给函数计算用）。

为什么不用 oss2：oss2 是源码包，没有 manylinux wheel；打成 zip 塞进函数会带上
Windows 编译的 C 扩展，在 Linux 运行时会直接崩。这里只实现函数需要的三个操作：

    put_object(bucket, key, body)        写对象，返回 ETag
    get_object(bucket, key)              读对象，返回 (bytes, etag)
    presign_get(bucket, key, expires)    生成预签名 GET URL（V1 签名）

签名算法是 OSS 的 V1：

    Authorization = "OSS " + AccessKeyId + ":" + base64(hmac_sha1(secret, string_to_sign))
    PUT: string_to_sign = "PUT\\n{md5}\\n{type}\\n{date}\\n/{bucket}/{key}"
    GET: string_to_sign = "GET\\n\\n\\n{date}\\n/{bucket}/{key}"
    预签名: string_to_sign = "GET\\n\\n\\n{expires}\\n/{bucket}/{key}"
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import formatdate


def _sign(secret, string_to_sign):
    digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"),
                      hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def _host(bucket, endpoint):
    endpoint = endpoint.replace("https://", "").replace("http://", "").rstrip("/")
    return f"{bucket}.{endpoint}"


def put_object(bucket, endpoint, key, body, access_id, secret, content_type="application/json"):
    """上传一个对象，返回 ETag。"""
    date = formatdate(usegmt=True)
    resource = f"/{bucket}/{key}"
    string_to_sign = f"PUT\n\n{content_type}\n{date}\n{resource}"
    authorization = f"OSS {access_id}:{_sign(secret, string_to_sign)}"
    url = f"https://{_host(bucket, endpoint)}/{key}"
    request = urllib.request.Request(url, data=body, method="PUT", headers={
        "Date": date,
        "Content-Type": content_type,
        "Authorization": authorization,
    })
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.headers.get("ETag", "")
    except urllib.error.HTTPError as exc:
        raise IOError(f"PUT {key} 失败: HTTP {exc.code} {exc.read()[:200]!r}") from exc


def get_object(bucket, endpoint, key, access_id, secret):
    """读一个对象，返回 (body, etag)；不存在返回 (None, None)。"""
    date = formatdate(usegmt=True)
    resource = f"/{bucket}/{key}"
    string_to_sign = f"GET\n\n\n{date}\n{resource}"
    authorization = f"OSS {access_id}:{_sign(secret, string_to_sign)}"
    url = f"https://{_host(bucket, endpoint)}/{key}"
    request = urllib.request.Request(url, method="GET", headers={
        "Date": date, "Authorization": authorization,
    })
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.read(), response.headers.get("ETag")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, None
        raise IOError(f"GET {key} 失败: HTTP {exc.code}") from exc


def presign_get(bucket, endpoint, key, access_id, secret, expires_in=300):
    """生成预签名 GET URL（V1）。"""
    expires = int(time.time()) + int(expires_in)
    resource = f"/{bucket}/{key}"
    string_to_sign = f"GET\n\n\n{expires}\n{resource}"
    signature = _sign(secret, string_to_sign)
    return (f"https://{_host(bucket, endpoint)}/{key}"
            f"?OSSAccessKeyId={access_id}&Expires={expires}"
            f"&Signature={urllib.parse.quote(signature, safe='')}")
