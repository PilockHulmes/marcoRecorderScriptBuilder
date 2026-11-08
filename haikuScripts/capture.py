"""兼容壳 —— 实现在 :mod:`maplebot.capture`。

这里只补上 `haikuScripts` 这一侧的默认值：

- 窗口标题：从本地配置读（见 ``maplebot/settings.py``），仓库默认 ``MapleStory``
- 素材目录 ``haikuScripts/assets``（绝对路径，不再依赖当前工作目录）
- 其他玩家检测：关闭（已改由 ``botCheckSolver.hasPplInMap()`` 负责，见 returnToPoint.py）
- 符文 / 黑屏 / 符文 buff / @bot 检测：关闭
- 截屏间隔：0.1 秒

保留 `capture.WINDOW_NAME`（`windowFocusLib.py` 在用）、`capture.config`、
`capture.utils` 这几个旧属性。
"""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from maplebot import config  # noqa: E402,F401  保留 capture.config 的旧用法
from maplebot import settings  # noqa: E402
from maplebot import utils  # noqa: E402,F401  保留 capture.utils 的旧用法
from maplebot.capture import Capture as _Capture  # noqa: E402

_ASSETS = pathlib.Path(__file__).resolve().parent / "assets"

#: 客户端窗口标题（真实值放 maplebot.local.json，仓库里只有通用默认值）
WINDOW_NAME = settings.window_title()


class Capture(_Capture):
    """haikuScripts 版 Capture：窗口名可传，除「找角色」外的检测全部关闭。"""

    def __init__(self, window_name=WINDOW_NAME):
        super().__init__(
            window_name=window_name,
            assets_dir=_ASSETS,
            detect_other=False,
            frame_interval=0.1,
        )
