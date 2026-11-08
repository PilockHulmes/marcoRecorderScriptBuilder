"""兼容壳 —— 实现在 :mod:`maplebot.utils`（纯函数，直接转发即可）。

保留 `utils.config` 这个旧属性（原文件里有 `import config as config`）。
"""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from maplebot import config  # noqa: E402,F401  保留 utils.config 的旧用法
from maplebot.utils import *  # noqa: E402,F401,F403
from maplebot.utils import (  # noqa: E402,F401
    convert_to_absolute,
    convert_to_relative,
    distance,
    filter_color,
    multi_match,
    single_match,
)
