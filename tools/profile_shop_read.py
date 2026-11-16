"""量一下"读一次商店"的 422 ms 花在哪。

不修改生产代码，只是按 read_visit 的顺序逐个调用并计时。
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from maplebot import shop, trade  # noqa: E402

FRAME_PATH = ROOT / "tests" / "fixtures" / "shop_frame.png"
ROUNDS = 5


def timed(label, fn, results):
    t0 = time.perf_counter()
    value = fn()
    results.setdefault(label, []).append((time.perf_counter() - t0) * 1000)
    return value


def main():
    frame = cv2.imdecode(np.fromfile(str(FRAME_PATH), dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        print("读不到样例")
        return 1

    # 预热：第一次会加载 OCR 模型
    shop.read_visit(frame)
    shop.read_visit(frame)

    results = {}
    for _ in range(ROUNDS):
        timed("1 找商店窗口 find_shop_window", lambda: trade.find_shop_window(frame), results)
        timed("2 行几何 read_rows", lambda: trade.read_rows(frame), results)
        timed("3 倒计时 OCR read_row_countdown",
              lambda: trade.read_row_countdown(frame), results)
        timed("4 金币/负重 read_cargo", lambda: trade.read_cargo(frame), results)

        templates = shop.load_icon_templates()
        rows = trade.read_rows(frame)
        for index, row in enumerate(rows[:3]):
            x, y, w, h = row.icon_box
            patch = frame[y:y + h, x:x + w]
            timed(f"5.{index} 图标识別 match_icon", lambda p=patch: shop.match_icon(p, templates), results)

        timed("6 整体 read_visit（现状）",
              lambda: shop.read_visit(frame), results)

    print(f"\n{'步骤':34} {'平均 ms':>8} {'占比':>7}")
    total = sum(sum(v) for k, v in results.items() if k.startswith("6")) / ROUNDS
    for key in sorted(results):
        avg = sum(results[key]) / len(results[key])
        share = f"{avg / total:.0%}" if key.startswith("6") else f"{avg / total:.0%}"
        print(f"{key:34} {avg:8.1f} {share:>7}")
    print(f"\n合计（read_visit）= {total:.1f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
