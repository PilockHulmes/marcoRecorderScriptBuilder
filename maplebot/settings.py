"""从本地配置读取个性化设置（客户端窗口标题、QQ 群名）。

仓库里**只留通用默认值**，真实值放在 ``maplebot.local.json``（``*.local.json`` 已 gitignore）：

```json
{
  "window_titles": ["MapleStory", "你的客户端窗口标题"],
  "qq_group": "你的群名"
}
```

也可以用环境变量临时覆盖：``MAPLEBOT_WINDOW``（逗号分隔多个标题）、``MAPLEBOT_QQ_GROUP``。
"""

import json
import os
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[1] / "maplebot.local.json"

#: 不含任何个人/服务器信息的默认值
DEFAULTS = {
    "window_titles": ["MapleStory"],
    "qq_group": "",
}


def load():
    """读取本地配置（不存在就用默认值，坏文件也忽略）。"""
    data = {key: (list(value) if isinstance(value, list) else value)
            for key, value in DEFAULTS.items()}
    if CONFIG_PATH.is_file():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
            for key in ("window_titles", "qq_group"):
                if key in raw and raw[key]:
                    data[key] = raw[key]
        except Exception:
            pass
    windows = os.environ.get("MAPLEBOT_WINDOW")
    if windows:
        data["window_titles"] = [item.strip() for item in windows.split(",") if item.strip()]
    group = os.environ.get("MAPLEBOT_QQ_GROUP")
    if group:
        data["qq_group"] = group
    return data


def window_titles():
    """候选窗口标题列表（第一个作为默认值）。"""
    titles = load()["window_titles"]
    return list(titles) if titles else list(DEFAULTS["window_titles"])


def window_title():
    """默认窗口标题。"""
    return window_titles()[0]


def qq_group():
    """要发图的 QQ 群名；没配置就是空字符串（发送会直接失败，不会乱发）。"""
    return str(load()["qq_group"])
