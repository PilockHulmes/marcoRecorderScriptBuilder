"""购物界面读取：把一帧 SHOP/CARGO 画面变成一条可记录的观察。

职责（详见 TRADE_DESIGN.md 第 13 节）：

- 用当前地图判定商人（固定商人一对一；其它地图可能是随机商人）
- 读每一行：商品图标 -> good_id、买价、卖价
- 图标认不出时用视觉读商品名：名字认识就补存图标模板，名字不认识就落
  ``icons_unknown/`` 等人归类（见 :mod:`maplebot.icon_learn`）
- 读倒计时、金币、当前载重
- 输出一条"观察记录"，不做任何建议

不负责滚动拼接（那是 runtime 的事），不负责有效期与建议。
"""

import json
import logging
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import icon_learn, trade

ROOT = Path(__file__).resolve().parents[1]
GOODS_PATH = ROOT / "data" / "trade" / "goods.json"
MERCHANT_MAPS_PATH = ROOT / "data" / "trade" / "merchant_maps.json"
ICON_INDEX_PATH = ROOT / "data" / "trade" / "merchant_index.json"
ICON_DIR = ROOT / "data" / "trade" / "icons"
UNKNOWN_ICON_DIR = ROOT / "data" / "trade" / "icons_unknown"
GOOD_NAMES_PATH = ROOT / "data" / "trade" / "good_names.json"

#: 学习开关（默认开启；测试/离线解析可显式关掉）
LEARN_NAMES = True
LEARN_ICONS = True

#: 图标匹配：缩到 24x24 后比较，0.80 足够区分不同商品
ICON_MATCH_SIZE = (24, 24)
ICON_THRESHOLD = 0.80

logger = logging.getLogger(__name__)


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
                             "merchant": item.get("merchant", ""),
                             "game_name": item.get("game_name", "")}
    return out


def _load_image(path):
    try:
        image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        return None
    return image if image is not None and image.size else None


def load_icon_templates(icon_dir=None, index_path=None):
    """good_id -> 图标图。

    先按 ``merchant_index.json`` 登记的顺序读，再扫一遍 ``icon_dir`` 里
    ``<good_id>.png``：运行期学到的图标只要落了盘，下一次重新加载就能用。
    """
    icon_dir = Path(icon_dir) if icon_dir is not None else ICON_DIR
    index_path = Path(index_path) if index_path is not None else ICON_INDEX_PATH
    index = _read_json(index_path, {})
    goods = load_goods()
    templates = {}
    entries = index.get("icons", []) if isinstance(index, dict) else []
    if not isinstance(entries, list):
        entries = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        good_id = item.get("good_id")
        rel = item.get("file", "")
        path = ROOT / "data" / "trade" / rel
        if not good_id or not path.exists():
            continue
        image = _load_image(path)
        if image is not None:
            templates[good_id] = image      # 保存原始尺寸，按用途各自缩放
    try:
        paths = sorted(icon_dir.glob("*.png"))
    except Exception:
        paths = []
    for path in paths:
        good_id = path.stem
        if good_id in templates or good_id not in goods:
            continue                            # cargo_header / portal 等非商品跳过
        image = _load_image(path)
        if image is not None:
            templates[good_id] = image
    return templates



def match_icon(patch, templates):
    """返回 (good_id, score)。"""
    if patch is None or patch.size == 0:
        return "", 0.0
    query = cv2.resize(patch, ICON_MATCH_SIZE, interpolation=cv2.INTER_AREA)
    best, best_id = 0.0, ""
    for good_id, template in templates.items():
        small = cv2.resize(template, ICON_MATCH_SIZE, interpolation=cv2.INTER_AREA)
        result = cv2.matchTemplate(query, small, cv2.TM_CCOEFF_NORMED)
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


#: 货舱物品行（实测，@1368x800 整窗坐标；客户区 x-1, y-32）
CARGO_ICON_X = 546
CARGO_ICON_Y = 287
CARGO_ROW_H = 33
CARGO_ROWS = 8
CARGO_ICON = 35


def read_cargo_items(frame, templates=None):
    """读身上带着哪些货；只认商品，不读价格（最近購買金額不能当成本）。"""
    templates = templates if templates is not None else load_icon_templates()
    found = []
    for index in range(CARGO_ROWS):
        y = CARGO_ICON_Y + index * CARGO_ROW_H
        try:
            patch = trade.crop_box(frame, CARGO_ICON_X - 4, y - 4,
                                   CARGO_ICON + 10, CARGO_ICON + 10)
        except Exception:
            continue
        good_id, score = match_icon_half(patch, templates)
        if good_id and score >= 0.80:
            found.append(good_id)
    return found


#: 货舱图标是商店图标的 50%，用滑动匹配（不要去拉伸模板）
CARGO_ICON_SCALE = 0.5
CARGO_MATCH_THRESHOLD = 0.70


def match_icon_half(region, templates, scale=CARGO_ICON_SCALE):
    """在 region 里滑动 50% 大小的模板，返回 (good_id, score)。"""
    if region is None or region.size == 0:
        return "", 0.0
    best, best_id = 0.0, ""
    for good_id, template in templates.items():
        small = cv2.resize(template, (max(8, int(template.shape[1] * scale)),
                                      max(8, int(template.shape[0] * scale))),
                           interpolation=cv2.INTER_AREA)
        if small.shape[0] > region.shape[0] or small.shape[1] > region.shape[1]:
            continue
        result = cv2.matchTemplate(region, small, cv2.TM_CCOEFF_NORMED)
        if result.size:
            score = float(result.max())
            if score > best:
                best, best_id = score, good_id
    return (best_id if best >= CARGO_MATCH_THRESHOLD else ""), best


def identify(map_name):
    """地图 -> (merchant_id, merchant, kind)。"""
    entry = load_merchant_maps().get(map_name)
    if entry:
        # 优先用游戏内繁体名（截图文件名里带的），没有才退回文档简体名
        name = entry.get("game_name") or entry["merchant"]
        return entry["merchant_id"], name, "fixed"
    return "", "", "random" if map_name else "unknown"


def _load_templates(icon_dir=None, index_path=None):
    """调用 :func:`load_icon_templates`；默认路径时不传参，方便测试打桩。"""
    kwargs = {}
    if icon_dir is not None:
        kwargs["icon_dir"] = icon_dir
    if index_path is not None:
        kwargs["index_path"] = index_path
    return load_icon_templates(**kwargs)


def _row_side_and_price(row):
    """这一行是「他卖给我」还是「他收我的」，以及对应价格。"""
    buy = int(getattr(row, "buy_price", 0) or 0)      # 他卖给我
    sell = int(getattr(row, "sell_price", 0) or 0)    # 他收我的
    if buy > 0:
        return "sell", buy
    if sell > 0:
        return "buy", sell
    return "", 0


def _append_row(visit, good_id, row, score, goods):
    side, price = _row_side_and_price(row)
    if not side:
        return False
    visit.rows.append(Row(good_id, goods.get(good_id, {}).get("name", good_id),
                          side, price, score))
    return True


def _icon_key(patch):
    return "icon:%08x" % (zlib.crc32(patch.tobytes()) & 0xFFFFFFFF)


def read_visit(frame, map_name="", templates=None, *, learn_names=None,
               learn_icons=None, vision=None, names_path=None,
               icon_dir=None, unknown_dir=None, index_path=None):
    """解析一帧画面 -> Visit（不滚动，只读当前可见的行）。

    学习开关默认取模块常量 :data:`LEARN_NAMES` / :data:`LEARN_ICONS`；
    ``vision`` 可注入 ``ndarray -> str``（测试用假视觉，运行期走 DeepSeek）。
    所有学习失败都安静跳过，不影响这一帧的其它行。
    """
    learn_names = LEARN_NAMES if learn_names is None else bool(learn_names)
    learn_icons = LEARN_ICONS if learn_icons is None else bool(learn_icons)
    names_path = Path(names_path) if names_path is not None else GOOD_NAMES_PATH
    icon_dir_arg = icon_dir
    index_path_arg = index_path
    icon_dir = Path(icon_dir) if icon_dir is not None else ICON_DIR
    unknown_dir = Path(unknown_dir) if unknown_dir is not None else UNKNOWN_ICON_DIR

    visit = Visit(map=map_name)
    visit.merchant_id, visit.merchant, visit.kind = identify(map_name)
    templates = (templates if templates is not None
                 else _load_templates(icon_dir_arg, index_path_arg))
    goods = load_goods()
    names = (icon_learn.load_good_names(names_path)
             if (learn_names or learn_icons) else {})

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

        if good_id:
            _append_row(visit, good_id, row, score, goods)
            # 图标认出来了：顺手把这一行的商品名记进名字表（每个 good_id 一次）
            if (learn_names and patch is not None
                    and not icon_learn.has_name_for(good_id, names)):
                key = "name:" + good_id
                if icon_learn.should_attempt(key):
                    name = icon_learn.read_row_name(frame, row.icon_box, vision=vision)
                    if name:
                        if icon_learn.record_good_name(name, good_id,
                                                       path=names_path, mapping=names):
                            logger.info("[学习] 商品名 %s -> %s", name, good_id)
                    else:
                        icon_learn.note_failure(key)
            continue

        # 图标认不出来：先读名字，能从名字表反查到 good_id 就把图标补上
        if not learn_icons or patch is None or getattr(patch, "size", 0) == 0:
            continue
        icon_key = _icon_key(patch)
        if not icon_learn.should_attempt(icon_key):
            continue
        name = icon_learn.read_row_name(frame, row.icon_box, vision=vision)
        if not name:
            icon_learn.note_failure(icon_key)
            continue
        known_id = names.get(name, "")
        if known_id and known_id in goods:
            created = icon_learn.save_icon(known_id, patch, icon_dir=icon_dir)
            if created is not None or known_id not in templates:
                templates = _load_templates(icon_dir_arg, index_path_arg)
            _append_row(visit, known_id, row, 0.0, goods)
            if created is not None:
                logger.info("[学习] 缺少图标 %s（%s），已存到 %s",
                            known_id, name, created)
        elif icon_learn.should_attempt("unknown:" + name):
            path = icon_learn.save_unknown_icon(patch, unknown_dir=unknown_dir)
            icon_learn.note_failure("unknown:" + name)
            icon_learn.note_failure(icon_key)
            logger.warning("[学习] 认不出的商品名 %r，图标存到 %s", name, path)
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
