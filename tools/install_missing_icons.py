"""按"读到的商品名"定位行，再裁图标——比"最低分那一行"可靠。

文件名 = good_id；先把 good_id 映射到可能的商品名（doc 简体名 + 已知繁体别名），
再用视觉读每一行的名字，匹配上哪行就裁哪行。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from maplebot import icon_learn, shop, trade  # noqa: E402

SRC = ROOT / "screenshots" / "trading" / "missing_goods"
ICONS = ROOT / "data" / "trade" / "icons"
SHEET = ROOT / "detections" / "installed_icons_sheet.png"

# 这 7 件货的名字（doc 简体 + 我们见过的繁体写法）
ALIASES = {
    "fine_silk": ["精致丝绸", "精緻絲綢", "刺繡的布料", "刺绣的布料"],
    "legendary_tonic": ["传说中的补药", "傳說中的補藥", "傳說的精神劑", "传说的精神剂"],
    "monster_meat": ["怪物肉", "怪物的肉"],
    "refined_black_crystal": ["精炼黑水晶", "精煉黑水晶", "精煉的黑水晶", "精炼的黑水晶"],
    "refined_lithium": ["提炼的锂", "提煉的鋰", "精煉的鋰", "精炼的锂"],
    "top_vitamin": ["顶级维他命", "頂級維他命", "最高級維他命", "最高级维他命"],
    "wild_ginseng": ["山参", "山蔘"],
}


def load(path):
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


def main():
    force = "--force" in sys.argv
    installed = []
    for path in sorted(SRC.glob("*.png")):
        good_id = path.stem
        target = ICONS / f"{good_id}.png"
        if target.exists() and not force:
            print(f"[skip] {good_id} 已有图标（--force 可覆盖）")
            continue
        frame = load(path)
        if frame is None or not trade.find_shop_window(frame):
            print(f"[skip] {path.name} 没有商店窗口")
            continue
        rows = trade.read_rows(frame)
        wanted = ALIASES.get(good_id, [])
        chosen = None
        for index, row in enumerate(rows):
            name = icon_learn.read_row_name(frame, row.icon_box)
            hit = any(alias in name or name in alias for alias in wanted) if name else False
            print(f"  {path.name} 行{index}: 读出 {name!r} {'← 命中' if hit else ''}")
            if hit and chosen is None:
                chosen = (index, row)
        if chosen is None:
            print(f"[fail] {path.name} 没找到名字对得上的行")
            continue
        index, row = chosen
        x, y, w, h = row.icon_box
        patch = frame[y:y + h, x:x + w]
        cv2.imencode(".png", patch)[1].tofile(str(target))
        installed.append((good_id, patch))
        print(f"[ok] {good_id} <- 行{index}（{path.name}）")

    if not installed:
        print("\n没有新装的")
        return 0

    tpl = shop.load_icon_templates()
    print("\n自检：")
    cells = []
    for good_id, patch in installed:
        got, score = shop.match_icon(patch, tpl)
        flag = "OK" if got == good_id else "!!"
        print(f"  [{flag}] {good_id} -> {got or '(认不出)'} {score:.3f}")
        big = cv2.resize(patch, (63 * 3, 63 * 3), interpolation=cv2.INTER_NEAREST)
        cv2.putText(big, good_id[:12], (3, 18), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, (0, 0, 255), 1)
        cells.append(big)
    cv2.imencode(".png", np.hstack(cells))[1].tofile(str(SHEET))
    print("\n对照图:", SHEET)
    return 0


if __name__ == "__main__":
    sys.exit(main())
