"""把"我的脚本"和"程序内部"逐步骤对照，找出中间产物的差异。

不修改任何生产代码，只是把 trade 里的私有函数按顺序调用一遍。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from maplebot import trade  # noqa: E402

BASE = r"C:\Users\PilockHulmes\.dsh\attachments\v1\objects"
SHOTS = [
    ("单独A(期望50)", BASE + r"\ed\ed5e577e42fee8bf41c00ac475339dd2113be3b54d0b6c83ce550eb7e1ee1e15"),
    ("单独B(期望7923)", BASE + r"\12\1268012dbe814704e6ca0447d40dee5250054c6013d6841125dcacecf8cfa52c"),
]


def manual(frame, x, y, w, h):
    """我的脚本做法：直接在保存的图上按帧坐标裁。"""
    return frame[y:y + h, x:x + w]


def main():
    for name, path in SHOTS:
        frame = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        print(f"\n=== {name}  size={frame.shape}")
        box = trade.CARGO_COINS_ONLY
        print(f"  常量 CARGO_COINS_ONLY = {box}（客户区坐标）")

        program = trade._crop(frame, box)
        print(f"  程序 _crop         -> shape={None if program is None else program.shape}")

        # _crop 的坐标换算
        screen = trade.crop_box(frame, *box) if hasattr(trade, "crop_box") else None
        print(f"  程序 crop_box      -> {type(screen).__name__}")

        mine = manual(frame, box[0] + 1, box[1] + 32, box[2], box[3])
        print(f"  我的 f[y:y+h,x:x+w] -> shape={mine.shape}")

        if program is not None and mine is not None:
            same = program.shape == mine.shape and np.array_equal(program, mine)
            print(f"  两者是否逐像素相同: {same}")

        for label, crop in (("程序", program), ("我的", mine)):
            if crop is None:
                print(f"  {label}: None")
                continue
            up = cv2.resize(crop, (crop.shape[1] * 3, crop.shape[0] * 3),
                            interpolation=cv2.INTER_CUBIC)
            print(f"  {label} 原图 OCR : {trade._ocr_text(crop, mode='light')!r}")
            print(f"  {label} 放大 OCR : {trade._ocr_text(up, mode='light')!r}")
            print(f"  {label} 逐位读   : {trade._digits_of_run(crop)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
