"""把金币识别时真正喂给 OCR 的图导出来（区分两种货舱布局）。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from maplebot import trade  # noqa: E402

BASE = r"C:\Users\PilockHulmes\.dsh\attachments\v1\objects"
CASES = [
    ("单独货舱 7923", BASE + r"\12\1268012dbe814704e6ca0447d40dee5250054c6013d6841125dcacecf8cfa52c", "only"),
    ("单独货舱 50", BASE + r"\ed\ed5e577e42fee8bf41c00ac475339dd2113be3b54d0b6c83ce550eb7e1ee1e15", "only"),
    ("商店货舱 0", str(ROOT / "tests" / "fixtures" / "shop_frame.png"), "shop"),
]
OUT = ROOT / "detections"


def render(label, frame, profile):
    box = trade.CARGO_COINS_ONLY if profile == "only" else trade.CARGO_COINS_SHOP
    strip = trade._crop(frame, box)
    if strip is None:
        print(f"{label}: 取不到")
        return None
    print(f"{label}: box={box} shape={strip.shape} "
          f"整段OCR={trade._ocr_text(strip, mode='light')!r}")

    # 金色段（程序里就是这么找的）
    run = trade._rightmost_gold_run(strip)
    print(f"   金色段={run}")

    cells = []
    if run is not None:
        x0, x1 = run
        width = x1 - x0
        count = max(1, int(round(width / trade.COIN_DIGIT_PITCH)))
        step = width / count
        for index in range(count):
            left = max(0, int(round(x0 + index * step)) - 2)
            right = min(strip.shape[1], int(round(x0 + (index + 1) * step)) + 2)
            cell = strip[:, left:right]
            big = cv2.resize(cell, (cell.shape[1] * 4, cell.shape[0] * 4),
                             interpolation=cv2.INTER_NEAREST)
            text = trade._ocr_text(big, mode="light") or trade._ocr_text(big, mode="raw") or ""
            painted = cv2.copyMakeBorder(big, 18, 4, 4, 4, cv2.BORDER_CONSTANT,
                                         value=(255, 255, 255))
            cv2.putText(painted, f"{index}:{text.strip() or '?'}", (4, 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 200), 1)
            cells.append(painted)

    raw = cv2.resize(strip, (strip.shape[1] * 3, strip.shape[0] * 3),
                     interpolation=cv2.INTER_NEAREST)
    raw = cv2.copyMakeBorder(raw, 18, 4, 4, 4, cv2.BORDER_CONSTANT,
                             value=(255, 255, 255))
    cv2.putText(raw, f"{label} 原条带 x3", (4, 14), cv2.FONT_HERSHEY_SIMPLEX,
                0.42, (0, 120, 0), 1)
    cells.insert(0, raw)

    height = max(c.shape[0] for c in cells)
    cells = [cv2.copyMakeBorder(c, 0, height - c.shape[0], 0, 0,
                                cv2.BORDER_CONSTANT, value=(255, 255, 255))
             for c in cells]
    return np.hstack(cells)


def main():
    rows = []
    for label, path, profile in CASES:
        frame = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            print(f"{label}: 读不到图")
            continue
        row = render(label, frame, profile)
        if row is not None:
            rows.append(row)
    if not rows:
        return 1
    width = max(r.shape[1] for r in rows)
    rows = [cv2.copyMakeBorder(r, 0, 6, 0, width - r.shape[1],
                               cv2.BORDER_CONSTANT, value=(255, 255, 255))
            for r in rows]
    sheet = np.vstack(rows)
    path = OUT / "coin_cells.png"
    cv2.imencode(".png", sheet)[1].tofile(str(path))
    print("导出:", path, sheet.shape)
    return 0


if __name__ == "__main__":
    sys.exit(main())
