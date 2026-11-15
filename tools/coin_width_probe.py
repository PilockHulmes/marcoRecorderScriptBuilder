"""量一量金色数字的宽度规律，给"按固定字宽逐位识别"定参数。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from maplebot import trade  # noqa: E402

SAMPLES = [
    ("tests/fixtures/shop_frame.png", "0", 1),
    ("detections/only_now.png", "5733", 4),
    ("detections/cargo_count_now.png", "31518", 5),
    (r"C:\Users\PilockHulmes\.dsh\attachments\v1\objects\12"
     r"\1268012dbe814704e6ca0447d40dee5250054c6013d6841125dcacecf8cfa52c", "7923", 4),
]


def main():
    for path, expected, digits in SAMPLES:
        frame = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            print(f"{path}: 读不到")
            continue
        strip = trade._crop(frame, trade.CARGO_COINS_SHOP)
        if strip is None:
            print(f"{path}: 取不到金币区")
            continue
        hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (12, 90, 150), (40, 255, 255))
        cols = (mask > 0).sum(axis=0)
        xs = np.where(cols)[0]
        if not len(xs):
            print(f"{path}: 没有金色像素")
            continue
        width = int(xs.max() - xs.min() + 1)
        ocr = trade._ocr_text(trade._gold_only(strip), mode="light")
        print(f"{Path(path).name:24} 期望{expected:6} 金色宽{width:3}px "
              f"位数{digits} 每字{width / digits:.2f}px OCR={ocr!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
