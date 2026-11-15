"""把未知图标整理成对照表：网格排列、带编号和数量，方便人眼认。

输出：
  detections/unknown_sheet.png   对照图（每格 3 倍放大，编号 + 张数）
  detections/unknown_sheet.txt   编号 -> 文件列表（我按你说的编号去改数据）
"""

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

UNKNOWN = ROOT / "data" / "trade" / "icons_unknown"
OUT_PNG = ROOT / "detections" / "unknown_sheet.png"
OUT_TXT = ROOT / "detections" / "unknown_sheet.txt"
SAME = 0.90
PER_ROW = 6
SCALE = 4
CELL = 63 * SCALE
PAD = 10
LABEL_H = 22


def load(path):
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


def similar(a, b):
    if a is None or b is None or a.shape != b.shape:
        return 0.0
    return float(cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED).max())


def main():
    images = [(p, load(p)) for p in sorted(UNKNOWN.glob("*.png"))]
    images = [(p, img) for p, img in images if img is not None]

    groups = []
    for path, img in images:
        for group in groups:
            if any(similar(img, other) >= SAME for _p, other in group):
                group.append((path, img))
                break
        else:
            groups.append([(path, img)])

    rows = -(-len(groups) // PER_ROW)
    sheet = np.full((rows * (CELL + LABEL_H + PAD) + PAD,
                     PER_ROW * (CELL + PAD) + PAD, 3), 255, np.uint8)
    lines = []
    for index, group in enumerate(groups):
        row, col = divmod(index, PER_ROW)
        x = PAD + col * (CELL + PAD)
        y = PAD + row * (CELL + LABEL_H + PAD)
        cell = cv2.resize(group[0][1], (CELL, CELL), interpolation=cv2.INTER_NEAREST)
        sheet[y + LABEL_H:y + LABEL_H + CELL, x:x + CELL] = cell
        label = f"#{index + 1}  x{len(group)}"
        cv2.putText(sheet, label, (x + 2, y + 16), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 0, 0), 1, cv2.LINE_AA)
        names = sorted({p.with_suffix(".txt").read_text(encoding="utf-8").strip()
                        for p, _i in group if p.with_suffix(".txt").exists()})
        lines.append(f"#{index + 1:02d}  {len(group)} 张"
                     + (f"  名字: {'、'.join(names)}" if names else "  名字: 未记录"))
        for path, _img in group:
            lines.append(f"      {path.name}")

    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".png", sheet)[1].tofile(str(OUT_PNG))
    OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
    print(f"对照图: {OUT_PNG}  ({len(groups)} 种，{len(images)} 张)")
    print(f"编号表: {OUT_TXT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
