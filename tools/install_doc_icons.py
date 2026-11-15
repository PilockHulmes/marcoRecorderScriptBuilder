"""把文档抠出来的波动货图标装进模板库，并先做一次质量校验。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

DOC_ICONS = ROOT / "detections" / "doc_icons"
ICONS = ROOT / "data" / "trade" / "icons"
GOODS = ROOT / "data" / "trade" / "goods.json"

NAME_TO_ID = {
    "提炼的锂": "refined_lithium",
    "精炼黑水晶": "refined_black_crystal",
    "丝绸布料": "silk_fabric",
    "山参": "wild_ginseng",
    "精致丝绸": "fine_silk",
    "金块": "gold_bar",
    "黄金桃子": "golden_peach",
    "皇帝的绸缎": "imperial_satin",
    "虎皮": "tiger_pelt",
    "贵族的绸缎": "noble_satin",
    "光辉钻石": "radiant_diamond",
    "怪物肉": "monster_meat",
    "传说中的补药": "legendary_tonic",
    "顶级紫水晶": "top_amethyst",
    "顶级维他命": "top_vitamin",
}


def load(path):
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


def main():
    templates = {p.stem: load(p) for p in ICONS.glob("*.png")}
    templates = {k: v for k, v in templates.items() if v is not None}
    print(f"现有模板 {len(templates)} 个\n")

    to_install = []
    for name, good_id in NAME_TO_ID.items():
        path = DOC_ICONS / f"{name}.png"
        if not path.exists():
            print(f"  [skip] 没有抠出来的图：{name}")
            continue
        img = load(path)
        has = good_id in templates
        if has:
            # 已有游戏内模板：只用来验证文档抠图是否一致
            score = float(cv2.matchTemplate(
                cv2.resize(templates[good_id], (63, 63)), img,
                cv2.TM_CCOEFF_NORMED).max())
            print(f"  {name:8} {good_id:22} 已有模板，与文档图一致度 {score:.3f}")
        else:
            to_install.append((good_id, name, img))
            print(f"  {name:8} {good_id:22} 缺模板 -> 准备安装")

    if not to_install:
        print("\n没有需要安装的")
        return 0

    print(f"\n安装 {len(to_install)} 个：")
    for good_id, name, img in to_install:
        target = ICONS / f"{good_id}.png"
        cv2.imencode(".png", img)[1].tofile(str(target))
        print(f"  {target.name} <- {name}")

    # 装完再自检：新模板能不能被自己的匹配器认出来
    from maplebot import shop
    tpl = shop.load_icon_templates()
    print("\n自检（用 shop.match_icon 认自己）：")
    for good_id, name, img in to_install:
        got, score = shop.match_icon(img, tpl)
        flag = "OK" if got == good_id else "!!"
        print(f"  [{flag}] {name:8} -> {got or '(认不出)'} {score:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
