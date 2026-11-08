"""兼容壳 —— 真正的全局状态在 :mod:`maplebot.config`，且**就是同一个模块对象**。

以前 `haikuScripts/config.py` 与 `auto-maple/src/config.py` 各有一份，谁写谁读
不是同一份，于是出现「capture 标定完了，脚本读到的还是 (0, 0)」。

这里用 `sys.modules[__name__] = 共享模块` 把别名接上，所以下面这些写法都不用改：

    import config
    import src.config
    from config import player_position
    config.player_position

代价是：本文件不能也不该再定义任何变量（加了也不会生效，因为模块对象被替换了）。
"""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from maplebot import config as _config  # noqa: E402

sys.modules[__name__] = _config
