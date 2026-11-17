"""GUI 入口（打包用）。

冻结后 `__file__` 在 _MEIPASS 里，数据都在那儿；OCR 模型也随包带上。
"""

import os
import sys
from pathlib import Path


def main():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    os.environ.setdefault("PADDLEOCR_HOME", str(root / ".paddleocr"))
    from maplebot.gui import run_gui

    return run_gui()          # 0=正常退出，2=已经有实例在跑


if __name__ == "__main__":
    sys.exit(main())
