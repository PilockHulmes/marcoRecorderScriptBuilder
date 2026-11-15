"""按"图标槽的浅灰底"定位每格图标，不依赖等距网格。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

SRC = ROOT / "detections" / "doc_image7.jpeg"
OUT_DIR = ROOT / "detections" / "doc_icons"
SHEET = ROOT / "detections" / "doc_icons_sheet.png"

COLS, ROWS = 5, 3
NAMES = [
    "提炼的锂", "精炼黑水晶", "丝绸布料", "山参", "精致丝绸",
    "金块", "黄金桃子", "皇帝的绸缎", "虎皮", "贵族的绸缎",
    "光辉钻石", "怪物肉", "传说中的补药", "顶级紫水晶", "顶级维他命",
]


def find_slot(cell):
    """在格子里找"浅灰方形槽"，返回 (x, y, w, h) 或 None。"""
    hsv = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
    # 浅灰：饱和度低、亮度中高
    mask = cv2.inRange(hsv, (0, 0, 150), (180, 60, 240))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < 40 or h < 40:
            continue
        ratio = w / h
        if not 0.75 <= ratio <= 1.35:
            continue
        area = w * h
        if best is None or area > best[0]:
            best = (area, x, y, w, h)
    return None if best is None else best[1:]


def main():
    doc = cv2.imdecode(np.fromfile(str(SRC), dtype=np.uint8), cv2.IMREAD_COLOR)
    height, width = doc.shape[:2]
    cell_w, cell_h = width // COLS, height // ROWS
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cells, missing = [], []
    for index, name in enumerate(NAMES):
        row, col = divmod(index, COLS)
        cell = doc[row * cell_h:(row + 1) * cell_h, col * cell_w:(col + 1) * cell_w]
        slot = find_slot(cell)
        if slot is None:
            missing.append(name)
            patch = np.zeros((63, 63, 3), np.uint8)
        else:
            x, y, w, h = slot
            # 槽里有 8px 左右的亮边框，往里收一点只留图标
            inset = max(4, int(w * 0.10))
            patch = cell[y + inset:y + h - inset, x + inset:x + w - inset]
            patch = cv2.resize(patch, (63, 63), interpolation=cv2.INTER_AREA)
        cv2.imencode(".png", patch)[1].tofile(str(OUT_DIR / f"{name}.png"))
        big = cv2.resize(patch, (63 * 3, 63 * 3), interpolation=cv2.INTER_NEAREST)
        cv2.putText(big, str(index + 1), (4, 20), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (0, 0, 255), 2)
        cells.append(big)

    rows = [np.hstack(cells[r * COLS:(r + 1) * COLS]) for r in range(ROWS)]
    cv2.imencode(".png", np.vstack(rows))[1].tofile(str(SHEET))
    print("定位失败:", missing if missing else "无")
    print("对照表:", SHEET)
    return 0


if __name__ == "__main__":
    sys.exit(main())
