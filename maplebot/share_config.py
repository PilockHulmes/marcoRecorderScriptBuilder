"""共享功能的服务配置。

配置来源（按优先级）：

1. 环境变量：``MAPLE_TRADE_SHARE_ENDPOINT`` / ``..._BUCKET`` / ``..._TOKEN``
2. 数据目录下的 ``share.json``（不会进仓库）

里面只放**客户端**需要的东西：

    {"endpoint": "https://oss-cn-hangzhou.aliyuncs.com",
     "bucket": "…", "token": "共享用的口令",
     "upload_url": "https://…",   # 中转函数地址（写请求走它）
     "read_prefix": "https://…/merchants/"}   # 公共读前缀（读请求直连）

**绝不放 AccessKey**：客户端只需要公共读 + 中转口令。开发机想直连调试时，
才另外通过环境变量 ``OSS_ACCESS_KEY_ID`` / ``OSS_ACCESS_KEY_SECRET`` 注入。
"""

from __future__ import annotations

import json
import os

from . import paths as paths_module

CONFIG_NAME = "share.json"


def config_path():
    return paths_module.data_root() / CONFIG_NAME


def load_config():
    """读配置；没有就返回空 dict（共享功能自动关闭）。"""
    config = {}
    path = config_path()
    try:
        if path.exists():
            config.update(json.loads(path.read_text(encoding="utf-8")) or {})
    except Exception:
        pass
    for key, env in (("endpoint", "MAPLE_TRADE_SHARE_ENDPOINT"),
                     ("bucket", "MAPLE_TRADE_SHARE_BUCKET"),
                     ("token", "MAPLE_TRADE_SHARE_TOKEN"),
                     ("upload_url", "MAPLE_TRADE_SHARE_UPLOAD_URL"),
                     ("read_prefix", "MAPLE_TRADE_SHARE_READ_PREFIX")):
        value = os.environ.get(env)
        if value:
            config[key] = value
    return config


def save_config(config):
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def enabled():
    """配置齐全才启用共享。"""
    config = load_config()
    return bool(config.get("bucket") and config.get("token"))


def dev_credentials():
    """开发机直连 OSS 用的密钥（只在环境变量里，不落盘）。"""
    key_id = os.environ.get("OSS_ACCESS_KEY_ID")
    secret = os.environ.get("OSS_ACCESS_KEY_SECRET")
    if key_id and secret:
        return key_id, secret
    return None, None
