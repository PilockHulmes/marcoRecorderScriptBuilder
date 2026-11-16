"""再往里拆一层：read_rows 内部每一行做了什么、各花多少毫秒。"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from maplebot import trade  # noqa: E402

FRAME_PATH = ROOT / "tests" / "fixtures" / "shop_frame.png"
ROUNDS = 5


def main():
    frame = cv2.imdecode(np.fromfile(str(FRAME_PATH), dtype=np.uint8), cv2.IMREAD_COLOR)
    trade.read_rows(frame)                      # 预热 OCR

    acc = {}
    def bump(key, ms):
        acc.setdefault(key, []).append(ms)

    for _ in range(ROUNDS):
        list_box = trade._box(frame, trade.LIST_BOX)
        list_bottom = list_box[1] + list_box[3]
        for top in trade.ROW_TOPS:
            icon_box = trade._box(frame, (trade.ICON_BOX[0], top,
                                          trade.ICON_BOX[2], trade.ICON_BOX[3]))
            if icon_box[1] >= list_bottom:
                break
            t0 = time.perf_counter()
            present = trade._row_present(frame, icon_box, clip_bottom=list_bottom)
            bump("a 判断这行有没有东西 _row_present", (time.perf_counter()-t0)*1000)
            if not present:
                continue
            partial = icon_box[1] + icon_box[3] > list_bottom
            t0 = time.perf_counter()
            name_crop = trade._crop(frame, (trade.NAME_BOX[0], top + 1,
                                            trade.NAME_BOX[2], trade.NAME_BOX[3]))
            name = trade._ocr_text(name_crop, mode="white", upscale=trade.NAME_UPSCALE,
                                   interpolation=cv2.INTER_NEAREST)
            bump("b 商品名 OCR _ocr_text(white)", (time.perf_counter()-t0)*1000)
            if partial:
                continue
            for label, dy in (("c 买价 OCR _read_price", trade.BUY_DY),
                              ("d 卖价 OCR _read_price", trade.SELL_DY)):
                t0 = time.perf_counter()
                trade._read_price(frame, top, dy)
                bump(label, (time.perf_counter()-t0)*1000)

    print(f"\n{'步骤':36} {'次数':>5} {'平均 ms':>8} {'单次商店合计 ms':>14}")
    grand = 0.0
    for key in sorted(acc):
        vals = acc[key]
        avg = sum(vals) / len(vals)
        per_read = sum(vals) / ROUNDS
        grand += per_read
        print(f"{key:36} {len(vals):5} {avg:8.1f} {per_read:14.1f}")
    print(f"\nread_rows 内部合计（每次商店读取）≈ {grand:.1f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
