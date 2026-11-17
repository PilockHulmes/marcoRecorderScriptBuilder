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

from . import goodnames
from . import logbook
from . import icon_learn, trade
from . import paths as paths_module

ROOT = Path(__file__).resolve().parents[1]
GOODS_PATH = paths_module.trade_dir() / "goods.json"
MERCHANT_MAPS_PATH = paths_module.trade_dir() / "merchant_maps.json"
ICON_INDEX_PATH = paths_module.trade_dir() / "merchant_index.json"
_TEMPLATE_CACHE = {}
ICON_DIR = paths_module.trade_dir() / "icons"
UNKNOWN_ICON_DIR = paths_module.trade_dir() / "icons_unknown"
GOOD_NAMES_PATH = paths_module.trade_dir() / "good_names.json"

#: 学习开关（默认开启；测试/离线解析可显式关掉）
#: 学商品名 / 学未知图标：45 个商品已经齐了，默认关闭。
#: 关掉之后每次读商店不再对每一行名字做 OCR（省时间），也不会再写文件。
#: 需要临时复原时传 `learn_names=True` / `learn_icons=True`。
#: 商店刷新的上限（秒）。超过这个值的读数一定是错的。
MAX_REFRESH_SEC = 360

LEARN_NAMES = False
LEARN_ICONS = False

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
    # 图标模板不再每次读盘（45 个 PNG ≈ 9 ms）：按路径缓存一份
    global _TEMPLATE_CACHE
    key = (str(icon_dir or ICON_DIR), str(index_path or ICON_INDEX_PATH))
    cached = _TEMPLATE_CACHE.get(key)
    if cached is not None:
        return cached

    icon_dir = Path(icon_dir) if icon_dir is not None else ICON_DIR
    index_path = Path(index_path) if index_path is not None else ICON_INDEX_PATH
    index = _read_json(index_path, {})
    goods = load_goods()
    templates = IconTemplates()
    entries = index.get("icons", []) if isinstance(index, dict) else []
    if not isinstance(entries, list):
        entries = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        good_id = item.get("good_id")
        rel = item.get("file", "")
        path = paths_module.trade_dir() / rel
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
    _TEMPLATE_CACHE[key] = templates
    return templates



class IconTemplates(dict):
    """图标模板表。自带一个"缩放结果"缓存，避免每次匹配都重新 resample。

    缓存挂在对象自身上，而不是用 ``id(templates)`` 当键——id 会被复用，
    不同模板表会撞车（这个坑被测试抓到过）。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.resized = {}


def _scaled(templates, good_id, size, cache_key):
    """取缩放到 ``size`` 的模板；同一个模板只 resample 一次。"""
    cache = getattr(templates, "resized", None)
    template = templates.get(good_id)
    if template is None:
        return None
    if cache is None:                 # 普通 dict（测试里常见）：不缓存
        return cv2.resize(template, size, interpolation=cv2.INTER_AREA)
    key = (cache_key, good_id)
    hit = cache.get(key)
    if hit is not None:
        return hit
    image = cv2.resize(template, size, interpolation=cv2.INTER_AREA)
    cache[key] = image
    return image


#: 货舱格子的识别缓存：格子像素摘要 -> good_id（同一格没变就不用重比）
_CARGO_CELL_CACHE = {}
_CARGO_CELL_CACHE_MAX = 256


def match_icon(patch, templates, candidates=None):
    """返回 (good_id, score)。

    ``candidates`` 给了就只比这些 good_id（知道商人是谁时，只比他那几样货），
    全都没过阈值再退回比全部——防止认错商人时彻底认不出商品。
    """
    if patch is None or patch.size == 0:
        return "", 0.0
    query = cv2.resize(patch, ICON_MATCH_SIZE, interpolation=cv2.INTER_AREA)
    best, best_id = _match_best(query, templates, candidates, ICON_MATCH_SIZE)
    if best >= ICON_THRESHOLD or not candidates:
        return (best_id if best >= ICON_THRESHOLD else ""), best
    # 候选里没有够像的（商人表可能不准）→ 退回全量再比一次
    best, best_id = _match_best(query, templates, None, ICON_MATCH_SIZE)
    return (best_id if best >= ICON_THRESHOLD else ""), best


def _match_best(query, templates, candidates, size):
    """在 ``candidates``（None = 全部）里找最像的模板。"""
    ids = candidates if candidates is not None else list(templates)
    best, best_id = 0.0, ""
    for good_id in ids:
        small = _scaled(templates, good_id, size, ("icon", size))
        if small is None or small.shape[:2] != size[::-1]:
            continue
        result = cv2.matchTemplate(query, small, cv2.TM_CCOEFF_NORMED)
        if result.size:
            score = float(result.max())
            if score > best:
                best, best_id = score, good_id
    return best, best_id


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
    """'01:18' -> 78。读不出、或读到不可能的值（>360 秒）都返回 0。

    商店刷新是 3~5 分钟；出现过把 03:00 读成 30:00 的情况（1800 秒），
    那种记录会污染看板的倒计时和"有效期"，所以超过 6 分钟一律作废。
    """
    if not text:
        return 0
    digits = "".join(ch if ch.isdigit() else ":" for ch in str(text))
    parts = [p for p in digits.split(":") if p]
    try:
        if len(parts) >= 2:
            value = int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 1:
            value = int(parts[0])
        else:
            return 0
    except ValueError:
        return 0
    return value if 0 <= value <= MAX_REFRESH_SEC else 0


#: 货舱物品行（实测，@1368x800 整窗坐标；客户区 x-1, y-32）
CARGO_ICON_X = 556
CARGO_ICON_Y = 284
CARGO_ROW_H = 33
CARGO_ROWS = 8
CARGO_ICON = 31


#: 商店开着时，货舱面板挪到右边，位置和「只开货舱」时不同
CARGO_SHOP_ICON_X = 685
CARGO_SHOP_ICON_Y = 285
CARGO_SHOP_ROW_H = 33
CARGO_SHOP_ROWS = 6
CARGO_SHOP_ICON = 31
CARGO_COUNT_SHOP = (896, 298, 46, 20)   # 行右侧的「N 個」


# 货舱面板定位：标题模板找到后，图标原点相对它的偏移（实测）


#: 上次找到的 CARGO 标题位置（按画面尺寸记）
_CARGO_ORIGIN_HINT = {}

#: 从 CARGO 文字左上角到"物品格原点"的偏移（帧坐标，两种布局实测一致）
CARGO_ORIGIN_DX = -108
CARGO_ORIGIN_DY = 78


def _find_cargo_title(frame):
    """找货舱面板标题 "CARGO" 的位置（帧坐标）；找不到返回 None。

    用 ``anchors/cargo_title.png``（只有 CARGO 文字），**不含玩家角色**——
    之前用的 ``cargo_header.png`` 是从我的角色画面截的，别人拿到就对不上。
    """
    from . import anchors as anchors_module

    patch = anchors_module.load_patches().get("cargo")
    if patch is None:
        return None
    height, width = frame.shape[:2]
    hint = _CARGO_ORIGIN_HINT.get((width, height))
    pad = 12
    if hint is not None:
        x0 = max(0, hint[0] - pad)
        y0 = max(0, hint[1] - pad)
        window = frame[y0:y0 + patch.shape[0] + 2 * pad,
                       x0:x0 + patch.shape[1] + 2 * pad]
        if (window.shape[0] >= patch.shape[0]
                and window.shape[1] >= patch.shape[1]):
            result = cv2.matchTemplate(window, patch, cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(result)
            if score >= 0.85:
                found = (loc[0] + x0, loc[1] + y0)
                _CARGO_ORIGIN_HINT[(width, height)] = found
                return found
    try:
        result = cv2.matchTemplate(frame, patch, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(result)
        if score < 0.85:
            return None
        _CARGO_ORIGIN_HINT[(width, height)] = (loc[0], loc[1])
        return (loc[0], loc[1])
    except Exception:
        return None


def _cargo_origin(frame):
    """用货舱标题定位面板，返回图标原点（**整窗坐标**）；定位不到返回 None。

    标题位置是固定的，所以先在上次找到的位置附近找（<1 ms），
    找不到才全屏匹配。偏移量对"商店右侧货舱"和"单独货舱"都成立。
    """
    title = _find_cargo_title(frame)
    if title is None:
        return None
    offset = trade.client_offset(frame)
    return (title[0] + CARGO_ORIGIN_DX + offset[0],
            title[1] + CARGO_ORIGIN_DY + offset[1])


def _count_items(frame, layout, templates):
    """在给定的坐标套路上数一数能认出几个商品（用来判断该用哪套坐标）。"""
    start_x, start_y, row_h, rows, icon = layout
    count = 0
    for index in range(rows):
        try:
            crop = trade.crop_box(frame, start_x, start_y + index * row_h, icon, icon)
        except Exception:
            continue
        if crop is None or crop.size == 0:
            continue
        good_id, score = match_icon_half(crop, templates)
        if good_id and score >= CARGO_MATCH_THRESHOLD:
            count += 1
    return count


def _cached_icon_half(patch, templates):
    """货舱格子识别（带像素摘要缓存）：格子没变就直接复用上次结果。"""
    if patch is None or patch.size == 0:
        return "", 0.0
    key = hash(patch.tobytes())
    hit = _CARGO_CELL_CACHE.get(key)
    if hit is not None:
        return hit[0], hit[1]
    result = match_icon_half(patch, templates)
    if len(_CARGO_CELL_CACHE) >= _CARGO_CELL_CACHE_MAX:
        _CARGO_CELL_CACHE.clear()
    _CARGO_CELL_CACHE[key] = result
    return result


def read_cargo_items(frame, templates=None, profile="only", with_counts=False):
    """读身上带着哪些货；只认商品，不读价格（最近購買金額不能当成本）。

    ``profile``：``only`` = 只开货舱（居中）；``shop`` = 商店开着时右侧的货舱面板。
    """
    templates = templates if templates is not None else load_icon_templates()
    origin = _cargo_origin(frame)
    if origin is not None:
        # 面板位置靠标题定位，行距/图标尺寸用商店那套（两种布局一致）
        start_x, start_y = origin
        row_h, rows, icon = CARGO_SHOP_ROW_H, CARGO_SHOP_ROWS, CARGO_SHOP_ICON
    else:
        # 定位不到就两套坐标都试一遍，谁读到的商品多用谁
        best_layout, best_count = None, -1
        for layout in ("shop", "only"):
            if layout == "shop":
                probe = (CARGO_SHOP_ICON_X, CARGO_SHOP_ICON_Y,
                         CARGO_SHOP_ROW_H, CARGO_SHOP_ROWS, CARGO_SHOP_ICON)
            else:
                probe = (CARGO_ICON_X, CARGO_ICON_Y, CARGO_ROW_H,
                         CARGO_ROWS, CARGO_ICON)
            found = _count_items(frame, probe, templates)
            if found > best_count:
                best_layout, best_count = probe, found
        start_x, start_y, row_h, rows, icon = best_layout
    found = []
    for index in range(rows):
        y = start_y + index * row_h
        try:
            patch = trade.crop_box(frame, start_x - 4, y - 4, icon + 10, icon + 10)
        except Exception:
            continue
        good_id, score = _cached_icon_half(patch, templates)
        if good_id and score >= 0.80:
            if with_counts:
                count = read_cargo_count(frame, origin=(start_x, start_y),
                                         icon=icon, row_h=row_h, index=index)
                found.append((good_id, count))
            else:
                found.append(good_id)
    return found


def read_cargo_count(frame, origin=None, icon=None, row_h=None, index=0):
    """读货舱第 index 行的件数（行右侧的 "135 個"）。

    以前是"裁 4 个位置 × 2 种模式投票"，因为不知道数字在哪，而且同一行里
    还有 `最近購買金額: 1620`，裁偏就会读到价格。现在改成：

    1. 裁这条行的右半段（足够宽，不用猜）；
    2. 用细体数字模板找"金色笔画分组"；
    3. **取最右边那一组**——件数永远在行尾；
    4. 位数/范围校验。

    一次裁剪、一次比对，约 1 ms。
    """
    if origin is None:
        return None
    start_x, start_y = origin
    icon = icon or CARGO_SHOP_ICON
    row_h = row_h or CARGO_SHOP_ROW_H
    y = start_y + index * row_h - 4

    band = None
    try:
        band = trade.crop_box(frame, start_x + 120, y, 220, icon + 8)
    except Exception:
        band = None
    if band is not None and band.size:
        groups = trade.digits_module.read_groups_at(band, family="thin", kind="gold")
        for text, _span in reversed(groups):          # 从右往左取第一个合法的
            if text.isdigit() and 1 <= len(text) <= 4:
                value = int(text)
                if 0 <= value <= 9999:
                    return value

    # 兜底：只读一次（不再投票）
    try:
        crop = trade.crop_box(frame, start_x + 211, y + 13, 46, 20)
    except Exception:
        return None
    if crop is None or crop.size == 0:
        return None
    text = trade._ocr_text(crop, mode="light") or ""
    digits_text = "".join(ch for ch in text if ch.isdigit())
    return int(digits_text) if digits_text else None


#: 货舱图标是商店图标的 50%，用滑动匹配（不要去拉伸模板）
CARGO_ICON_SCALE = 0.5
CARGO_MATCH_THRESHOLD = 0.70


def match_icon_half(region, templates, scale=CARGO_ICON_SCALE, candidates=None):
    """在 region 里滑动 50% 大小的模板，返回 (good_id, score)。"""
    if region is None or region.size == 0:
        return "", 0.0
    best, best_id = 0.0, ""
    ids = candidates if candidates is not None else list(templates)
    for good_id in ids:
        template = templates.get(good_id)
        if template is None:
            continue
        size = (max(8, int(template.shape[1] * scale)),
                max(8, int(template.shape[0] * scale)))
        small = _scaled(templates, good_id, size, ("half", scale))
        if small is None:
            continue
        if small.shape[0] > region.shape[0] or small.shape[1] > region.shape[1]:
            continue
        result = cv2.matchTemplate(region, small, cv2.TM_CCOEFF_NORMED)
        if result.size:
            score = float(result.max())
            if score > best:
                best, best_id = score, good_id
    return (best_id if best >= CARGO_MATCH_THRESHOLD else ""), best


def goods_name(good_id, goods=None):
    """商品在界面上的显示名：优先游戏内繁体名，其次文档简体名。"""
    table = goods if goods is not None else load_goods()
    item = table.get(good_id) or {}
    return item.get("name_tw") or item.get("name") or good_id


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


#: 各档位的合法价格区间（见 TRADE_DESIGN.md §2）。越界一定是读错了。
TIER_PRICE_RANGE = {
    "tier1": (10, 25),
    "tier2": (35, 75),
    "volatile": (100, 300),
}


def _price_plausible(good, price):
    """价格是否落在该档位的合法区间内。未知档位一律放行。"""
    if price is None:
        return False
    span = TIER_PRICE_RANGE.get((good or {}).get("tier"))
    if span is None:
        return True
    return span[0] <= int(price) <= span[1]


def _append_row(visit, good_id, row, score, goods):
    side, price = _row_side_and_price(row)
    if not side:
        return False
    # 价格越界（例如把 19 读成 1）说明这一帧读错了，宁可不记，也不要污染记录簿
    if price is not None and not _price_plausible(goods.get(good_id, {}), price):
        price = None
    visit.rows.append(Row(good_id, goods_name(good_id, goods),
                          side, price, score))
    return True


def _icon_key(patch):
    return "icon:%08x" % (zlib.crc32(patch.tobytes()) & 0xFFFFFFFF)


def read_visit(frame, map_name="", templates=None, *, cache=None, now=None, learn_names=None,
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
    names = icon_learn.load_good_names(names_path)

    try:
        visit.refresh_in = countdown_seconds(trade.read_row_countdown(frame))
    except Exception:
        pass
    try:
        cargo = trade.read_cargo(frame, cache=cache)
        coins = getattr(cargo, "coins", None)
        visit.coins = int(coins) if coins is not None else None
        visit.weight = int(getattr(cargo, "weight", 0) or 0)
        visit.capacity = int(getattr(cargo, "capacity", 0) or 0)
        visit.cargo_known = True     # 金币/负重确实读到了（0 也是真实值）
        # 金币读不准（千位分隔被读成多一位）时不要硬当 0，否则"买不起"会吞掉建议
        if getattr(visit, "coins", None) is None:
            visit.coins = 10 ** 9
            visit.coins_known = False
        else:
            visit.coins_known = True
        if visit.capacity < 50:      # 读残了（'0/135' 可能只认出 '13'），用已知固定值
            visit.capacity = 135

    except Exception:
        pass

    # 货舱可能整块读不到（窗口没显示 cargo、或解析失败）：此时金币和容量都是 0。
    # 按 0 算会得出"你买不起"，于是一条建议都不给；宁可当作"未知"。
    if visit.capacity <= 0:
        visit.capacity = 135

    # 商店刷新是"到期时刻"跳变：用它判断缓存里的价格还能不能用
    deadline = None
    if now is not None:
        deadline = float(now) + float(getattr(visit, "refresh_in", 0) or 0)
    try:
        rows = trade.read_rows(frame, cache=cache,
                               cache_tag=getattr(visit, "merchant_id", ""),
                               deadline=deadline)
    except Exception:
        rows = []

    # 知道是哪个商人了，就只比他那几样货的图标（认不出来会自动退回全量）
    merchant_id = getattr(visit, "merchant_id", "") or ""
    candidates = None
    if merchant_id:
        candidates = [gid for gid, item in goods.items()
                      if item.get("seller") == merchant_id] or None

    for row in rows:
        if getattr(row, "partial", False):
            continue
        patch = None
        try:
            x, y, w, h = row.icon_box
            patch = frame[y:y + h, x:x + w]
        except Exception:
            pass
        good_id, score = match_icon(patch, templates, candidates)

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

        # 图标认不出来：读这一行的名字兜底。
        # 这一步**不受学习开关控制**——它是正常识别流程的一部分，否则图标模板
        # 一旦有错，这件货就永远读不出来（貴族的布料踩过）。
        name = ""
        try:
            name = icon_learn.read_row_name(frame, row.icon_box, vision=vision)
        except Exception:
            name = ""
        known_id = goodnames.resolve(name, names, goods) if name else ""
        if known_id and known_id in goods:
            _append_row(visit, known_id, row, 0.0, goods)
            # 顺手把这个图标补进模板（写盘仍然受学习开关控制）
            if (learn_icons and patch is not None and known_id not in templates):
                icon_key = _icon_key(patch)
                if icon_learn.should_attempt(icon_key):
                    created = icon_learn.save_icon(known_id, patch, icon_dir=icon_dir)
                    if created is not None:
                        templates = _load_templates(icon_dir_arg, index_path_arg)
                        logger.info("[学习] 缺少图标 %s（%s），已存到 %s",
                                    known_id, name, created)
                    else:
                        icon_learn.note_failure(icon_key)
            continue

        # 图标、名字都认不出：记日志，方便事后从群友的日志里发现
        logbook.log_event("商品未認出", 名稱=name or "(讀不出名字)",
                          商人=merchant_id or "?",
                          圖標=("?" if patch is None else
                              f"{patch.shape[1]}x{patch.shape[0]}"),
                          買價=getattr(row, "buy_price", None),
                          賣價=getattr(row, "sell_price", None))
        logger.info("认不出这行商品：图标没匹配、名字=%r", name or "(读不出)")
        if name:
            icon_learn.save_unknown_icon(patch, unknown_dir=unknown_dir, read_name=name)

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
