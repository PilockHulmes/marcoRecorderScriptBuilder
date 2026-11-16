"""打包用的入口：只做一次"能不能跑通"的自检。

冻结后 `__file__` 在 _MEIPASS 里，所以数据文件都能从 ROOT 找到。
"""

import os
import sys
from pathlib import Path


def main():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    os.environ.setdefault("PADDLEOCR_HOME", str(root / ".paddleocr"))

    import cv2
    import numpy as np

    from maplebot import trade

    fixture = root / "tests" / "fixtures" / "shop_frame.png"
    print("fixture:", fixture.exists())
    frame = cv2.imdecode(np.fromfile(str(fixture), dtype=np.uint8), cv2.IMREAD_COLOR)
    print("frame:", None if frame is None else frame.shape)
    cargo = trade.read_cargo(frame)
    print("cargo:", cargo)
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
