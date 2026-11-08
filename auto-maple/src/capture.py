"""兼容壳 —— 实现在 :mod:`maplebot.capture`。

这里只补上 `auto-maple` 这一侧的默认值：

- 窗口标题：从本地配置读（见 ``maplebot/settings.py``），仓库默认 ``MapleStory``
- 素材目录 ``auto-maple/assets``（绝对路径）
- 检测开关：其他玩家 / 符文 / 黑屏 / 符文 buff 开启，@bot 关闭（与改造前一致）
- 截屏间隔：0.05 秒
"""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from maplebot import config  # noqa: E402,F401  保留旧属性
from maplebot import settings  # noqa: E402
from maplebot import utils  # noqa: E402,F401  保留旧属性
from maplebot.capture import Capture as _Capture  # noqa: E402

_ASSETS = pathlib.Path(__file__).resolve().parents[1] / "assets"

#: 客户端窗口标题（真实值放 maplebot.local.json）
WINDOW_NAME = settings.window_title()


class Capture(_Capture):
    """auto-maple 版 Capture：无参数，检测开关按原实现。"""

    def __init__(self):
        super().__init__(
            window_name=WINDOW_NAME,
            assets_dir=_ASSETS,
            detect_rune=True,
            detect_blackscreen=True,
            detect_rune_buff=True,
            frame_interval=0.05,
        )
