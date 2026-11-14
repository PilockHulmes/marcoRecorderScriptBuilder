"""购物界面读取：把一帧 SHOP/CARGO 画面变成一条可记录的观察。

职责（详见 TRADE_DESIGN.md 第 13 节）：

- 用当前地图判定商人（固定商人一对一；其它地图可能是随机商人）
- 读每一行：商品图标 -> good_id、买价、卖价
- 读倒计时、金币、当前载重
- 输出一条"观察记录"，不做任何建议

不负责滚动拼接（那是 runtime 的事），不负责有效期与建议。
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import trade

ROOT = Path(__file__).resolve().parents[1]
GOODS_PATH = ROOT / "data" / "trade" / "goods.json"
MERCHANT_MAPS_PATH = ROOT / "data" / "trade" / "merchant_maps.json"
ICON_INDEX_PATH = ROOT / "data" / "trade" / "merchant_index.json"
ICON_DIR = ROOT / "data" / "trade" / "icons"

#: 图标匹配：缩到 24x24 后比较，0.80 足够区分不同商品
ICON_MATCH_SIZE = (24, 24)
ICON_THRESHOLD = 0.80


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def load_goods():
    data = _read_json(GOODS_PATH, {})
    return {g["id"]: g for g in data.get("goods", [])}


def load_merchant_maps():
    """地图 -> {merchant_id, merchant}"""
    data = _read_json(MERCHANT_MAPS_PATH, {})
    out = {}
    for item in data.values():
        map_name = item.get("map")
        if map_name:
            out[map_name] = {"merchant_id": item.get("merchant_id", ""),
                             "merchant": item.get("merchant", "")}
    return out


def load_icon_templates():
    """good_id -> 图标图（24x24）。"""
    index = _read_json(ICON_INDEX_PATH, {})
    templates = {}
    for item in index.get("icons", []):
        good_id = item.get("good_id")
        rel = item.get("file", "")
        path = ROOT / "data" / "trade" / rel
        if not good_id or not path.exists():
            continue
        image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            continue
        templates[good_id] = cv2.resize(image, ICON_MATCH_SIZE, interpolation=cv2.INTER_AREA)
    return templates


def match_icon(patch, templates):
    """返回 (good_id, score)。"""
    if patch is None or patch.size == 0:
        return "", 0.0
    query = cv2.resize(patch, ICON_MATCH_SIZE, interpolation=cv2.INTER_AREA)
    best, best_id = 0.0, ""
    for good_id, template in templates.items():
        result = cv2.matchTemplate(query, template, cv2.TM_CCOEFF_NORMED)
        if result.size:
            score = float(result.max())
            if score > best:
                best, best_id = score, good_id
    return (best_id if best >= ICON_THRESHOLD else ""), best


@dataclass
class Row:
    good_id: str
    good_name: str
    side: str          # "sell" = 他卖给我；"buy" = 他收我的
    price: int
    icon_score: float = 0.0


@dataclass
class Visit:
    map: str = ""
    merchant_id: str = ""
    merchant: str = ""
    kind: str = "unknown"          # fixed | random | unknown
    refresh_in: int = 0
    coins: int = 0
    weight: int = 0
    capacity: int = 0
    rows: list = field(default_factory=list)

    def to_dict(self):
        return {
            "map": self.map, "merchant_id": self.merchant_id, "merchant": self.merchant,
            "merchant_kind": self.kind, "refresh_in": self.refresh_in,
            "coins": self.coins, "weight": self.weight, "capacity": self.capacity,
            "rows": [{"good_id": r.good_id, "good": r.good_name, "side": r.side,
                      "price": r.price, "icon_score": round(r.icon_score, 3)}
                     for r in self.rows],
        }


def countdown_seconds(text):
    """'01:18' -> 78。读不出返回 0。"""
    if not text:
        return 0
    digits = "".join(ch if ch.isdigit() else ":" for ch in str(text))
    parts = [p for p in digits.split(":") if p]
    try:
        if len(parts) >= 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 1:
            return int(parts[0])
    except ValueError:
        pass
    return 0


#: CARGO 里物品行的扫描参数（1368x800 整窗坐标，由 trade.crop_box 换算）
CARGO_LIST_X = 700
CARGO_LIST_Y = 258
CARGO_ROW_H = 50
CARGO_ROWS = 6
CARGO_ICON = 44


def read_cargo_items(frame, templates=None):
    """读身上带着哪些货（只认商品，数量暂不读）。"""
    templates = templates if templates is not None else load_icon_templates()
    found = []
    for index in range(CARGO_ROWS):
        y = CARGO_LIST_Y + index * CARGO_ROW_H
        try:
            patch = trade.crop_box(frame, CARGO_LIST_X, y, CARGO_ICON, CARGO_ICON)
        except Exception:
            continue
        good_id, score = match_icon(patch, templates)
        if good_id and score >= 0.80:
            found.append(good_id)
    return found


def identify(map_name):
    """地图 -> (merchant_id, merchant, kind)。"""
    entry = load_merchant_maps().get(map_name)
    if entry:
        return entry["merchant_id"], entry["merchant"], "fixed"
    return "", "", "random" if map_name else "unknown"


def read_visit(frame, map_name="", templates=None):
    """解析一帧画面 -> Visit（不滚动，只读当前可见的行）。"""
    visit = Visit(map=map_name)
    visit.merchant_id, visit.merchant, visit.kind = identify(map_name)
    templates = templates if templates is not None else load_icon_templates()
    goods = load_goods()

    try:
        visit.refresh_in = countdown_seconds(trade.read_row_countdown(frame))
    except Exception:
        pass
    try:
        cargo = trade.read_cargo(frame)
        visit.coins = int(getattr(cargo, "coins", 0) or 0)
        visit.weight = int(getattr(cargo, "weight", 0) or 0)
        visit.capacity = int(getattr(cargo, "capacity", 0) or 0)
        if visit.capacity < 50:      # 读残了（'0/135' 可能只认出 '13'），用已知固定值
            visit.capacity = 135
    except Exception:
        pass

    try:
        rows = trade.read_rows(frame)
    except Exception:
        rows = []

    for row in rows:
        if getattr(row, "partial", False):
            continue
        patch = None
        try:
            x, y, w, h = row.icon_box
            patch = frame[y:y + h, x:x + w]
        except Exception:
            pass
        good_id, score = match_icon(patch, templates)
        buy = int(getattr(row, "buy_price", 0) or 0)      # 他卖给我
        sell = int(getattr(row, "sell_price", 0) or 0)    # 他收我的
        if good_id and buy > 0:
            visit.rows.append(Row(good_id, goods.get(good_id, {}).get("name", good_id),
                                  "sell", buy, score))
        elif good_id and sell > 0:
            visit.rows.append(Row(good_id, goods.get(good_id, {}).get("name", good_id),
                                  "buy", sell, score))
    return visit


def _main(argv=None):
    import sys

    args = argv or sys.argv[1:]
    if not args:
        print("用法: python -m maplebot.shop <截图.png> [地图名]")
        return 1
    path = Path(args[0])
    map_name = args[1] if len(args) > 1 else ""
    frame = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        print("读图失败:", path)
        return 1
    visit = read_visit(frame, map_name)
    print(json.dumps(visit.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
