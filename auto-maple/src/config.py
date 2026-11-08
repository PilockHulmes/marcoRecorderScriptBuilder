"""兼容壳 —— 真正的全局状态在 :mod:`maplebot.config`，且**就是同一个模块对象**。

`auto-maple/src/config.py` 原来是一份独立拷贝；现在与 `haikuScripts/config.py`
指向同一个模块，`import src.config` 不用改。
"""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from maplebot import config as _config  # noqa: E402

sys.modules[__name__] = _config
