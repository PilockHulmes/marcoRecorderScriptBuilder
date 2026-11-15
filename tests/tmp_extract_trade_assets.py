# -*- coding: utf-8 -*-
"""一次性素材抽取：从 15 张 trader_ui 全屏截图里裁出商人头像 + 商品图标模板。

输入  : screenshots/trading/trader_ui/*.png （1368×800，SHOP 窗口都在）
知识库: data/trade/goods.json
几何  : maplebot/trade.py（不改动它，只调用 read_rows / ROW_TOPS / ICON_BOX）

产出  : data/trade/merchants/<merchant_id>.png
        data/trade/icons/<good_id>.png
        data/trade/merchant_index.json

思路
----
1. 文件名就是屏幕上那个 NPC 的名字（繁体写法），先按文件名给出候选 merchant_id；
2. 用 ``trade.read_rows()`` 拿 3 个完整行的 icon_box，裁 63×63；
3. 三行里前两行是「该商人卖的两种货」，第三行是「他收的货」或「本波在售的波动商品」；
4. 商品图标按「24×24 三通道归一化相关 + HSV 直方图交」聚类，阈值 0.10；
5. 商品名来自对截图的逐行抄录（OCR 辅助 + 人工放大核对），再映射到 goods.json 的 good_id；
6. 用「前两行 good 的集合 == 该商人 sells 集合」反推商人、并验证聚类纯度。

游戏内名字和 goods.json 的攻略名不完全一样（例如 人蔘=桔梗、生水=矿泉水），
映射表见 ``NAME_TO_GOOD``；对不上的组合会在 merchant_index.json 里标 mismatch。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from maplebot import trade  # noqa: E402

SHOT_DIR = ROOT / "screenshots" / "trading" / "trader_ui"
GOODS_JSON = ROOT / "data" / "trade" / "goods.json"
OUT_DIR = ROOT / "data" / "trade"
MERCHANT_DIR = OUT_DIR / "merchants"
ICON_DIR = OUT_DIR / "icons"
INDEX_JSON = OUT_DIR / "merchant_index.json"

# ---------------------------------------------------------------- 几何
#: SHOP 窗口左上角的 NPC 立绘。窗口内容区从 x=415 / y≈225 开始；立绘会向上、向左
#: 溢出一部分（例如蘑菇帽、草帽），所以往上多留 5 px、往左只到窗口内沿，
#: 避免把窗口外的场景也裁进来（每张图的场景不同，会污染模板）。
PORTRAIT_BOX = (414, 220, 88, 68)  # (x, y, w, h) @1368×800

#: 图标取模板时只用满 3 行；第 4 行只有 ~15 px，做不了模板。
FULL_ROWS = 3

# ---------------------------------------------------------------- 匹配参数
#: 特征：内缩 6 px（避开槽位描边/波动商品的金框）→ 24×24 → 三通道各自 z-score；
#: 距离 = 0.6 × (1 - 三通道平均相关系数) + 0.4 × (1 - HSV 直方图交集)。
CROP_MARGIN = 6
FEAT_SIZE = 24
W_CORR = 0.6
W_HIST = 0.4
#: 聚类阈值。实测：同一商品的两张裁图距离 = 0.000（像素级相同），
#: 不同商品里最接近的一对（祖母綠碎片 vs 藍寶石碎片）= 0.146，
#: 取 0.10 正好落在空隙里。
CLUSTER_THRESHOLD = 0.10

# ---------------------------------------------------------------- 知识
#: 文件名（= 屏幕上的 NPC 名）→ merchant_id。文件名优先；后面还会用 sells 组合反推核对。
FILE_MERCHANT = {
    "卡勒奇沙": "ore_5",     # NPC「卡勒奇沙」/ 攻略「卡勒卡萨」
    "史來": "dour_4",        # NPC「史來」/ 攻略「史莱」
    "哲利": "ore_7",         # NPC「哲利」/ 攻略「哲里」
    "奇里營": "kobi_2",      # NPC「奇里營」/ 攻略「奇里文」
    "寇比": "kobi_5",        # NPC「寇比」/ 攻略「柯比」
    "幹員 0": "ore_4",       # NPC「幹員 0」/ 攻略「工作人员0」
    "查比爾": "kobi_7",      # NPC「查比爾」/ 攻略「扎比埃尔」
    "沙吉達": "dour_7",      # NPC「沙吉達」/ 攻略「萨哥特」
    "瑪帕": "kobi_4",        # 同名
    "石鉄": "kobi_1",        # NPC「石鉄」/ 攻略「石铁」
    "羅森": "ore_6",         # 同名
    "藍明": "kobi_3",        # NPC「藍明」/ 攻略「兰明」
    "財務大臣烏特宛": "kobi_6",  # NPC「財務大臣烏特宛」/ 攻略「伍德万」
    "道勒": "dour_5",        # NPC「道勒」/ 攻略「豆尔」
    "雅斯敏": "dour_6",      # NPC「雅斯敏」/ 攻略「雅思敏」
}

#: 每张截图前三行的**游戏内**商品名（繁体），逐张放大核对过（OCR 辅助）。
ROW_NAMES = {
    "卡勒奇沙": ("閃亮的鋼鐵塊", "祖母綠碎片", "金塊"),
    "史來": ("生水", "沙漠石榴", "沙漠的圍巾"),
    "哲利": ("黃金母礦", "鑽石碎片", "光輝鑽石"),
    "奇里營": ("礦石碎片", "藍寶石碎片", "最上級紫水晶"),
    "寇比": ("狐狸尾巴", "合成纖維", "人蔘"),
    "幹員 0": ("鋼鐵塊", "黃晶碎片", "動物性油"),
    "查比爾": ("沙漠的圍巾", "華麗的碎布", "皇帝的綢緞"),
    "沙吉達": ("動物性油", "沙漠番茄", "狐狸尾巴"),
    "瑪帕": ("棉花團", "海豹皮革", "動物性油"),
    "石鉄": ("人蔘", "蜂蜜", "柔軟的綢緞"),
    "羅森": ("銀的母礦", "黑水晶碎片", "生水"),
    "藍明": ("布塊", "棉", "豬肉"),
    "財務大臣烏特宛": ("柔軟的綢緞", "布料", "生水"),
    "道勒": ("仙人掌樹液", "仙桃果蜜", "蜂蜜"),
    "雅斯敏": ("豬肉", "白蛇湯", "黃金水蜜桃"),
}

#: 游戏内名 → goods.json 的 good_id。多数是同一商品的另一种译名。
NAME_TO_GOOD = {
    "人蔘": "balloon_flower",        # 攻略叫「桔梗」
    "蜂蜜": "natural_honey",
    "柔軟的綢緞": "soft_silk",        # 攻略叫「柔顺的丝绸」
    "銀的母礦": "silver_ore",         # 攻略叫「银原石」
    "黑水晶碎片": "black_crystal_shard",
    "生水": "mineral_water",          # 攻略叫「矿泉水」
    "棉花團": "cotton_ball",
    "海豹皮革": "otter_pelt",         # 攻略叫「水獭皮」
    "動物性油": "animal_fat",         # 攻略叫「动物性油脂」
    "布塊": "cloth_scrap",            # 攻略叫「布片」
    "棉": "cotton",                   # 攻略叫「棉花」
    "豬肉": "pork",
    "狐狸尾巴": "fox_tail",
    "合成纖維": "synthetic_oil",      # 攻略叫「合成石油」
    "礦石碎片": "ore_shard",
    "藍寶石碎片": "sapphire_shard",
    "最上級紫水晶": "top_amethyst",    # 攻略叫「顶级紫水晶」
    "鋼鐵塊": "steel_shard",          # 攻略叫「钢铁碎片」
    "黃晶碎片": "citrine_shard",
    "沙漠的圍巾": "desert_scarf",
    "華麗的碎布": "ornate_cloth_scrap",  # 攻略叫「华丽的布料碎片」
    "皇帝的綢緞": "imperial_satin",    # 攻略叫「皇帝的绸缎」
    "沙漠番茄": "desert_tomato",
    "沙漠石榴": "desert_pomegranate",
    "仙人掌樹液": "cactus_sap",        # 攻略叫「仙人掌刺液」
    "仙桃果蜜": "immortal_peach",      # 攻略叫「仙桃」
    "白蛇湯": "white_sugar",          # 攻略叫「白糖」——名字差得远，见报告
    "黃金水蜜桃": "golden_peach",      # 攻略叫「黄金桃子」
    "黃金母礦": "gold_ore",           # 攻略叫「金原石」
    "鑽石碎片": "diamond_shard",
    "閃亮的鋼鐵塊": "shining_steel_shard",  # 攻略叫「闪耀的钢铁碎片」
    "祖母綠碎片": "emerald_shard",
    "金塊": "gold_bar",
    "光輝鑽石": "radiant_diamond",     # 攻略叫「光辉钻石」
    "布料": "felt_cloth",             # 攻略叫「毛毡布料」
}


# ---------------------------------------------------------------- 小工具
def imread(path: Path):
    return trade.load_image(path)


def imwrite(path: Path, image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError(f"PNG 编码失败：{path}")
    buf.tofile(str(path))


def features(crop):
    """63×63 图标 → (三通道 z-score 的 24×24, HSV 直方图)。"""
    margin = CROP_MARGIN
    inner = crop[margin:crop.shape[0] - margin, margin:crop.shape[1] - margin]
    small = cv2.resize(inner, (FEAT_SIZE, FEAT_SIZE), interpolation=cv2.INTER_AREA)
    small = small.astype(np.float64)
    chans = []
    for ch in range(3):
        plane = small[:, :, ch]
        plane = plane - plane.mean()
        std = plane.std()
        chans.append(plane / std if std > 1e-6 else plane)
    hsv = cv2.cvtColor(inner, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [18, 4], [0, 180, 0, 256])
    cv2.normalize(hist, hist, 1.0, 0.0, cv2.NORM_L1)
    return np.stack(chans), hist


def distance(fa, fb) -> float:
    corr = float(np.mean([np.sum(fa[0][ch] * fb[0][ch]) / (FEAT_SIZE * FEAT_SIZE)
                          for ch in range(3)]))
    corr = max(-1.0, min(1.0, corr))
    hist = 1.0 - float(np.sum(np.minimum(fa[1], fb[1])))
    return W_CORR * (1.0 - corr) + W_HIST * hist


def complete_linkage(feats, threshold):
    """朴素凝聚聚类（complete linkage），返回 index 列表的列表。"""
    n = len(feats)
    dist = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = distance(feats[i], feats[j])
            dist[i][j] = dist[j][i] = d
    clusters = [[i] for i in range(n)]
    while len(clusters) > 1:
        best = None
        for a in range(len(clusters)):
            for b in range(a + 1, len(clusters)):
                d = max(dist[i][j] for i in clusters[a] for j in clusters[b])
                if best is None or d < best[0]:
                    best = (d, a, b)
        if best is None or best[0] > threshold:
            break
        _d, a, b = best
        clusters[a].extend(clusters[b])
        del clusters[b]
    return clusters


def sharpness(crop) -> float:
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def rows_via_trade(frame):
    """优先用 trade.read_rows()（任务要求）；OCR 不可用时退回固定几何。"""
    try:
        rows = trade.read_rows(frame)
        if len(rows) >= FULL_ROWS:
            return rows, "trade.read_rows"
    except Exception as exc:  # pragma: no cover - 仅当 OCR 环境坏掉
        print(f"  read_rows 失败，退回几何常量：{exc}")
    rows = []
    for top in trade.ROW_TOPS[:FULL_ROWS]:
        x, y, w, h = trade._box(frame, (trade.ICON_BOX[0], top, trade.ICON_BOX[2], trade.ICON_BOX[3]))
        rows.append(trade.Row(icon_box=(x, y, w, h), name_ocr="", buy_price=None,
                              sell_price=None, partial=False))
    return rows, "constants"


# ---------------------------------------------------------------- 主流程
def main(argv=None):
    parser = argparse.ArgumentParser(description="抽取商人头像 + 商品图标模板")
    parser.add_argument("--debug", action="store_true", help="打印每张图的明细")
    args = parser.parse_args(argv)

    goods_doc = json.loads(GOODS_JSON.read_text(encoding="utf-8"))
    goods = {g["id"]: g for g in goods_doc["goods"]}
    merchants = {m["id"]: m for m in goods_doc["merchants"]}
    # goods.json 的 sells / buys 写的是商品名，统一换成 good_id 再比对
    name_to_id = {g["name"]: g["id"] for g in goods_doc["goods"]}
    sells_set = {m["id"]: frozenset(name_to_id[n] for n in m["sells"])
                 for m in goods_doc["merchants"]}
    buys_set = {m["id"]: frozenset(name_to_id[n] for n in m["buys"])
                for m in goods_doc["merchants"]}
    sells_order = {m["id"]: [name_to_id[n] for n in m["sells"]]
                   for m in goods_doc["merchants"]}

    shots = sorted(SHOT_DIR.glob("*.png"))
    if len(shots) != 15:
        print(f"警告：trader_ui 下有 {len(shots)} 张图（预期 15）")

    items = []      # (stem, merchant_id, row_idx, good_id, crop, ocr_name)
    per_file = []   # 汇总
    detail_entries = []
    for path in shots:
        stem = path.stem
        if stem not in FILE_MERCHANT:
            print(f"跳过未知文件：{path.name}")
            continue
        merchant_id = FILE_MERCHANT[stem]
        names = ROW_NAMES[stem]
        frame = imread(path)
        rows, source = rows_via_trade(frame)
        if len(rows) < FULL_ROWS or any(r.partial for r in rows[:FULL_ROWS]):
            raise RuntimeError(f"{path.name} 前三行不完整，无法抽取")
        row_goods = [NAME_TO_GOOD[n] for n in names]
        got = []
        for idx in range(FULL_ROWS):
            x, y, w, h = rows[idx].icon_box
            crop = frame[y:y + h, x:x + w].copy()
            if crop.shape[0] != 63 or crop.shape[1] != 63:
                raise RuntimeError(f"{path.name} 第 {idx + 1} 行裁图尺寸 {crop.shape}，不是 63×63")
            items.append((stem, merchant_id, idx, row_goods[idx], crop, rows[idx].name_ocr))
            got.append(row_goods[idx])
        per_file.append({
            "file": path.name,
            "merchant_id": merchant_id,
            "row_goods": row_goods,
            "row_ocr": [r.name_ocr for r in rows],
            "row_prices": [(r.buy_price, r.sell_price) for r in rows],
            "row_partial": [r.partial for r in rows],
            "icon_boxes": [list(r.icon_box) for r in rows],
            "geometry_source": source,
        })
        if args.debug:
            print(path.name, merchant_id, got, [r.name_ocr for r in rows])

    # ---------------- 聚类
    feats = [features(it[4]) for it in items]
    clusters = complete_linkage(feats, CLUSTER_THRESHOLD)
    clusters.sort(key=lambda c: items[c[0]][3])

    purity_issues = []
    for cluster in clusters:
        labels = {items[i][3] for i in cluster}
        if len(labels) > 1:
            purity_issues.append({
                "labels": sorted(labels),
                "items": [(items[i][0], items[i][2] + 1) for i in cluster],
            })

    # 每个 good 选一张最清晰（重复样本像素级相同，sharpness 多为并列）
    icon_entries = []
    for cluster in clusters:
        labels = {items[i][3] for i in cluster}
        if len(labels) != 1:
            continue
        good_id = labels.pop()
        best = max(cluster, key=lambda i: (sharpness(items[i][4]), -i))
        crop = items[best][4]
        imwrite(ICON_DIR / f"{good_id}.png", crop)
        seen_in = []
        for i in cluster:
            mid = items[i][1]
            if mid not in seen_in:
                seen_in.append(mid)
        icon_entries.append({
            "good_id": good_id,
            "file": f"icons/{good_id}.png",
            "seen_in": seen_in,
            # 以下只进 debug 明细
            "_name": goods[good_id]["name"],
            "_tier": goods[good_id]["tier"],
            "_seen_count": len(cluster),
            "_source": f"{items[best][0]}.png:row{items[best][2] + 1}",
            "_sharpness": round(sharpness(crop), 2),
            "_distance_max": round(max(
                (distance(feats[i], feats[j]) for i in cluster for j in cluster), default=0.0), 4),
        })

    # ---------------- 头像
    merchant_entries = []
    for rec in per_file:
        stem = Path(rec["file"]).stem
        mid = rec["merchant_id"]
        frame = imread(SHOT_DIR / rec["file"])
        x, y, w, h = PORTRAIT_BOX
        portrait = frame[y:y + h, x:x + w].copy()
        imwrite(MERCHANT_DIR / f"{mid}.png", portrait)
        row_goods = rec["row_goods"]
        observed_sells = frozenset(row_goods[:2])
        # 用「前两行卖的两种货」反推商人
        candidates = [m for m, s in sells_set.items() if s == observed_sells]
        inferred = candidates[0] if len(candidates) == 1 else None
        sells_ok = observed_sells == sells_set[mid]
        order_ok = list(row_goods[:2]) == sells_order[mid]
        if not sells_ok:
            match = "mismatch"
        elif inferred is None:
            match = "unknown"
        else:
            match = "ok"
        # 第 3 行：收的货 / 波动商品
        third = row_goods[2]
        if third in buys_set[mid]:
            third_kind = "buy"
        elif third in goods and goods[third]["seller"] == mid and goods[third]["tier"] == "volatile":
            third_kind = "volatile_sell"
        else:
            third_kind = "unexpected"
        notes = []
        if not order_ok:
            notes.append("前两行显示顺序与 goods.json sells 顺序相反（集合一致）")
        if third_kind == "volatile_sell":
            notes.append(f"第 3 行是本波在售的波动商品「{goods[third]['name']}」")
        merchant_entries.append({
            "id": mid,
            "name": merchants[mid]["name"],
            "portrait": f"merchants/{mid}.png",
            "source": f"trader_ui/{rec['file']}",
            "goods_seen": list(row_goods[:2]),
            "match": match,
            "note": "；".join(notes) if notes else "",
        })
        detail_entries.append({
            "id": mid,
            "file": rec["file"],
            "in_game_names": ROW_NAMES[stem],
            "row_goods": row_goods,
            "ocr_names": rec["row_ocr"],
            "prices_buy_sell": rec["row_prices"],
            "icon_boxes": rec["icon_boxes"],
            "geometry_source": rec["geometry_source"],
            "observed_sells_set": sorted(observed_sells),
            "kb_sells": sells_order[mid],
            "sells_set_match": sells_ok,
            "sells_order_match": order_ok,
            "inferred_by_sells": inferred,
            "third_row": {"good_id": third, "kind": third_kind,
                          "name": goods[third]["name"]},
            "third_row_in_kb_buys": third in buys_set[mid],
        })

    covered = {e["good_id"] for e in icon_entries}
    missing = []
    for gid, g in goods.items():
        if gid not in covered:
            missing.append({
                "good_id": gid, "name": g["name"], "tier": g["tier"],
                "seller": g["seller"],
                "reason": "该商人本波没有把波动商品摆出来（列表只露出前 3 行：2 个卖货 + 第 1 个收货/波动货），截图中看不到它的图标",
            })

    # ---------------- 价格 × tier 审计（交叉验证 goods.json 的 price_tiers）
    tiers = goods_doc["price_tiers"]
    tier_audit = []
    for rec in per_file:
        mid = rec["merchant_id"]
        row_goods = rec["row_goods"]
        prices = rec["row_prices"]
        for idx in range(2):
            gid = row_goods[idx]
            price = prices[idx][0]
            band = tiers[goods[gid]["tier"]]["buy"]
            if price is not None and not (band[0] <= price <= band[1]):
                tier_audit.append({
                    "merchant": mid, "good_id": gid, "good": goods[gid]["name"],
                    "kb_tier": goods[gid]["tier"], "observed": price,
                    "kind": "买入价", "expected": band, "row": idx + 1,
                })
        third = row_goods[2]
        if third in buys_set[mid] and prices[2][1] is not None:
            band = tiers[goods[third]["tier"]]["sell"]
            price = prices[2][1]
            if not (band[0] <= price <= band[1]):
                tier_audit.append({
                    "merchant": mid, "good_id": third, "good": goods[third]["name"],
                    "kb_tier": goods[third]["tier"], "observed": price,
                    "kind": "卖出价", "expected": band, "row": 3,
                })

    unmatched = [{"file": p.name, "reason": "文件名不在已知 15 商人内"}
                 for p in shots if p.stem not in FILE_MERCHANT]

    payload = {
        "version": 1,
        "merchants": merchant_entries,
        "icons": [{k: v for k, v in e.items() if not k.startswith("_")} for e in icon_entries],
        "unmatched": unmatched,
        "missing_goods": missing,
    }
    INDEX_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------------- 控制台摘要
    print(f"截图 {len(per_file)} 张 / 裁出图标 {len(items)} 个 / 聚类 {len(clusters)} 簇 / "
          f"唯一商品 {len(icon_entries)} 个 / 缺失 {len(missing)} 个")
    print("阈值：", CLUSTER_THRESHOLD, "（类内 max =",
          round(max((e["_distance_max"] for e in icon_entries), default=0.0), 4), "）")
    print("簇纯度问题：", purity_issues if purity_issues else "无")
    bad = [m for m in merchant_entries if m["match"] != "ok"]
    print("match != ok：", bad if bad else "无")
    order_bad = [d["id"] for d in detail_entries if not d["sells_order_match"]]
    print("sells 顺序不一致：", order_bad)
    print("缺失商品：", [f"{m['name']}({m['good_id']})" for m in missing])
    print(f"价格与 goods.json tier 区间不符：{len(tier_audit)} 条")
    for a in tier_audit:
        print("  ", a["good"], a["good_id"], a["kb_tier"], a["observed"], a["expected"], a["kind"])

    if args.debug:
        debug_dir = ROOT / "tests" / "_probe"
        debug_dir.mkdir(exist_ok=True)
        (debug_dir / "extract_detail.json").write_text(json.dumps({
            "per_file": detail_entries,
            "purity_issues": purity_issues,
            "tier_audit": tier_audit,
            "clusters": [{
                "good_id": e["good_id"],
                "name": e["_name"],
                "tier": e["_tier"],
                "seen_in": e["seen_in"],
                "seen_count": e["_seen_count"],
                "source": e["_source"],
                "distance_max": e["_distance_max"],
            } for e in icon_entries],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
