"""共享内核。

原来 `haikuScripts/` 与 `auto-maple/src/` 各有一份几乎逐字相同的
`capture.py` / `config.py` / `utils.py`，本包是唯一实现；那两个目录里的同名文件
现在都只是薄壳（参数不同而已）。

模块分工：

- :mod:`maplebot.config` —— 进程内唯一的一份全局状态
- :mod:`maplebot.utils` —— 纯函数（模板匹配、坐标换算、颜色过滤）
- :mod:`maplebot.timing` —— 精确等待（睡眠 + 短自旋，不烧 CPU）
- :mod:`maplebot.win32` —— 窗口查找 / 矩形 / DPI
- :mod:`maplebot.minimap` —— 小地图定位（白色圆角边框）
- :mod:`maplebot.player` —— 小地图上的角色定位与跟踪（黄点 + 白圈）
- :mod:`maplebot.capture` —— 截屏线程 + 小地图识别
- :mod:`maplebot.botcheck` —— 挂机监测：面板检测 / 验证码读取 / 输入
- :mod:`maplebot.qq` —— 把截图发到 QQ 群（默认 dry_run）
- :mod:`maplebot.vision` —— 通用「图片 + 问题 → 文字」调用
- :mod:`maplebot.stop` —— 全局急停（stop key、按键记账、退出时松键）
- :mod:`maplebot.runner` —— 统一入口（`run.py` 的实现）
- :mod:`maplebot.rune` —— 符文面板定位 / 裁剪 / 按方向键
- :mod:`maplebot.rune_api` —— DeepSeek 视觉 API 封装（截图 → 4 个方向）
"""

__all__ = [
    "botcheck",
    "capture",
    "config",
    "minimap",
    "player",
    "qq",
    "runner",
    "rune",
    "rune_api",
    "stop",
    "timing",
    "trade",
    "utils",
    "vision",
    "win32",
]

__version__ = "2.0.0"
