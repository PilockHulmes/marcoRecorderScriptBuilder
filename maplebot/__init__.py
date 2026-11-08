"""共享内核。

原来 `haikuScripts/` 与 `auto-maple/src/` 各有一份几乎逐字相同的
`capture.py` / `config.py` / `utils.py`，本包是唯一实现；那两个目录里的同名文件
现在都只是薄壳（参数不同而已）。

模块分工：

- :mod:`maplebot.config` —— 进程内唯一的一份全局状态
- :mod:`maplebot.utils` —— 纯函数（模板匹配、坐标换算、颜色过滤）
- :mod:`maplebot.timing` —— 精确等待（睡眠 + 短自旋，不烧 CPU）
- :mod:`maplebot.win32` —— 窗口查找 / 矩形 / DPI
- :mod:`maplebot.capture` —— 截屏线程 + 小地图识别
- :mod:`maplebot.stop` —— 全局急停（stop key、按键记账、退出时松键）
- :mod:`maplebot.runner` —— 统一入口（`run.py` 的实现）
"""

__all__ = ["capture", "config", "runner", "stop", "timing", "utils", "win32"]

__version__ = "2.0.0"
