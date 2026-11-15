"""跑商助手 GUI：独立小窗，三块面板，分批刷新。

刷新节奏（详见 TRADE_DESIGN.md 第 15 节）：

    抓帧 / 地图跟踪     每 100ms
    读购物界面          0.4s（打开瞬间立刻读一次）
    读货舱              1.0s
    看板数据重建        2.0s
    窗口重绘            0.25s（倒计时在绘制时现算，所以每秒都在走）

逻辑与界面分离：画面 -> 状态的全部规则在 `maplebot.session.TradeSession`
（控制台版 `maplebot.runtime` 用的是同一个类）；`Controller` 只是它的薄壳，
测试不需要显示环境。
「商人看板」是 Canvas：商人 16×16 头像 + 商品 16×16 图标；PhotoImage 缓存在
`IconCache` 里并由调用方长期持有，否则 Tk 会回收图片、画布上什么都不显示。

看板布局（760×930 窗口）：

- **位置永久固定**：商人固定 15 个，按 ``merchant_id`` 的线路前缀
  （kobi < dour < ore）+ 数字序号排序；即使没有任何观察记录也全部渲染；
- 商人条目排成 **两列**（左列 8 个、右列 7 个），顺序固定所以位置固定；
- 每个商人固定 **2 列 × 4 行 = 8 个商品槽位**：先卖后收，均按
  ``data/trade/goods.json`` 的文件顺序；没有价格也占住同一个位置；
- 没有数据时标题照常显示、倒计时显示「未看過」、价格显示「—」；
- 过期或没有有效观察的价格一律显示「—」（浅灰）：卖/收 + 价格只有拿到
  未过期的真实数字时才分别用蓝色 / 橙色，商品名始终深灰；
- 商品名左对齐、买卖标签固定 x、价格右对齐（anchor），不用等宽字体；
- 只画 ``data/trade/merchant_maps.json`` 里的固定商人；随机商人不进看板。
"""

import time
from dataclasses import dataclass, field
from pathlib import Path

from . import shop
from . import trade
from .session import (BOARD_EVERY, CARGO_EVERY, LINE_ORDER, SHOP_EVERY, State,
                      TradeSession, _fixed_merchant_entries,
                      _merge_merchant_observations, _merchant_sort_key,
                      _observed_at, _row_merge_key, _safe)

REPAINT_EVERY = 0.25

ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "data" / "trade" / "icons"
PORTRAIT_DIR = ROOT / "data" / "trade" / "merchants"
#: 裁好的脸（``tools/build_faces.py`` 生成，尺寸不一但都只含头 + 少量肩）；
#: 显示层仍缩到 ICON_SIZE（16×16），优先用它，没有才退回整张立绘。
FACE_DIR = ROOT / "data" / "trade" / "merchants_face"

#: 窗口尺寸：宽度 380 -> 760（加倍），高度 620 -> 930（×1.5）。
#: 多出来的高度全部给商人看板，当前建议仍是固定 8 行。
ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
ICON_PATH = ASSETS_DIR / "app_icon.ico"

WINDOW_W = 1500
WINDOW_H = 730
ADVICE_ROWS = 4
ADVICE_COL_W = 420
ADVICE_COLS = 88
#: 首帧 canvas 还没实际宽度时的兜底（760 窗口减去内边距和滚动条）
DEFAULT_BOARD_W = WINDOW_W - 24

#: 看板尺寸 / 间距（TRADE_DESIGN.md 15.2 / 15.3）
ICON_SIZE = 16
HEAD_H = 22
ROW_H = 18
BLOCK_GAP = 2
BOARD_PAD = 4
ROW_INDENT = 10
ICON_GAP = 4

#: 商人两列 + 每个商人固定 2×4 商品槽位（永久同样的位置）
COLUMN_GAP = 12          # 两个商人列之间的空隙
# 档位配色沿用冒险岛稀有度：epic 紫 / unique 橙 / legend 绿，压暗到白底可读
TIER_COLORS = {
    "tier1": "#7B2FBE",
    "tier2": "#C77700",
    "volatile": "#1E8E3E",
}
TIER_RANK = {"tier1": 0, "tier2": 1, "volatile": 2}   # 紫 → 橙 → 绿
COLOR_ROW = "#212121"

GOODS_COLUMNS = 2        # 商品固定两列
SELL_ROWS = 3            # 左列：他卖的（2 普通 + 1 波动）
BUY_ROWS = 6             # 右列：他收的（4 普通 + 2 波动），波动价最值钱，必须常驻
GOODS_ROWS = BUY_ROWS    # 块高按较高的一列算
GOODS_SLOTS = SELL_ROWS + BUY_ROWS           # 每个商人固定 9 个槽位
MIN_MERCHANT_COL = 260   # 单列至少这么宽才排两列，窄窗口自动退回一列

#: 倒计时颜色（15.5）：>60s 绿、≤60s 黄、已过期灰、未看过浅灰
COLOR_GREEN = "#2e7d32"
COLOR_YELLOW = "#f9a825"
COLOR_GRAY = "#9e9e9e"
COLOR_UNSEEN = "#bdbdbd"
COLOR_ROW = "#333333"

#: 买卖方向色：卖=青色/蓝色，收=橙色（「卖/收」和价格用同一种颜色）
COLOR_SELL = "#1565c0"
COLOR_BUY = "#e65100"

#: 商品文字三段式定位（名字左对齐 / 标签固定 x / 价格右对齐）
PRICE_RIGHT_OFFSET = 2
LABEL_RIGHT_OFFSET = 52
NAME_MIN_GAP = 18

UNSEEN_TEXT = "未看過"
EXPIRED_TEXT = "已過期"
PRICE_EMPTY = "—"

HEAD_FONT = ("Microsoft YaHei", 9, "bold")
ROW_FONT = ("Microsoft YaHei", 9)


@dataclass
class BoardItem:
    """看板上的一个条目（商人标题或一件商品）以及它的矩形框。

    ``x/y/w/h`` 是布局阶段算好的坐标（像素），离屏测试直接打印这些值即可验证
    两列布局和边界；``owner`` 是所属商人，便于测试把商品分回商人。
    """

    kind: str                    # merchant | good | placeholder
    x: int
    y: int
    w: int
    h: int
    owner: str = ""
    text: str = ""               # 商人标题 / 商品名 / 空槽位的「—」
    suffix: str = ""             # 商人标题右侧的倒计时
    color: str = COLOR_ROW
    suffix_color: str = ""
    icon_kind: str = ""          # merchant | good | ""
    icon_key: str = ""
    anchor: str = "nw"
    # 商品槽位的固定字段：名字、标签、价格各自独立定位
    good_id: str = ""
    side: str = ""               # sell | buy | ""（空槽位）
    slot: int = -1               # 0..7 固定槽位序号；-1 = 非商品槽位
    label: str = ""              # 卖 / 收
    price_text: str = ""         # 价格数字 / 「—」
    name_x: int = 0              # 名字左 x（anchor="w"）
    label_x: int = 0             # 「卖/收」固定 x（anchor="w"）
    price_x: int = 0             # 价格右 x（anchor="e"）
    label_color: str = ""        # 「卖/收」和价格共用的颜色


@dataclass
class BoardLayout:
    """``layout_board()`` 的纯计算结果（不依赖 Tk）。"""

    width: int
    height: int
    columns: int                 # 实际使用的商人列数（1 / 2；空看板 0）
    column_width: int            # 每个商人列的宽度
    split: int = 0               # 左列放前 split 个商人
    items: list = field(default_factory=list)

    def of_kind(self, kind):
        return [item for item in self.items if item.kind == kind]


class Controller(TradeSession):
    """GUI 视图：逻辑全部在 :class:`maplebot.session.TradeSession`。

    保留这个名字是给 ``run_gui`` 和测试用的；它本身不增加任何行为。
    """


def _name(good_id):
    try:
        return shop.load_goods().get(good_id, {}).get("name", good_id)
    except Exception:
        return good_id


# ------------------------------------------------------------- 看板绘制素材
def status_color(seconds_left):
    """倒计时颜色（TRADE_DESIGN.md 15.5）。"""
    if seconds_left <= 0:
        return COLOR_GRAY
    if seconds_left <= 60:
        return COLOR_YELLOW
    return COLOR_GREEN


def format_duration(seconds):
    """把剩余秒数写成游戏里那样的 ``MM:SS`` 倒计时。

    - ``142`` → ``02:22``、``45`` → ``00:45``、``5`` → ``00:05``、``0`` → ``00:00``；
    - 分钟超过 99 位时按实际位数（``7200`` → ``120:00``），不再补齐两位；
    - 负数或读不出来的值按 0 处理。
    """
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        total = 0
    total = max(0, total)
    minutes, rest = divmod(total, 60)
    return f"{minutes:02d}:{rest:02d}"


def _pil_modules():
    """PIL 可选：没装就返回 (None, None)，退回 tk.PhotoImage。"""
    try:
        from PIL import Image, ImageTk
        return Image, ImageTk
    except Exception:
        return None, None


def _valid_key(key):
    """图标文件名只接受纯 id，挡住路径穿越和空值。"""
    return (isinstance(key, str) and bool(key)
            and "/" not in key and "\\" not in key
            and key not in (".", ".."))


def _load_photo(master, path, size, pil):
    """把一张 png 缩成 `size`×`size`，返回 (PhotoImage, 后端名)。

    PIL 可用时走 LANCZOS（商品 63×63、裁好的脸 32–54 见方、整张立绘 88×68
    都压到 16×16）；否则用 PhotoImage.subsample，按两轴各自最接近的整数倍缩小。
    """
    image_module, image_tk = pil
    if image_module is not None:
        with image_module.open(str(path)) as source:
            scaled = source.convert("RGBA").resize((size, size), image_module.LANCZOS)
        return image_tk.PhotoImage(scaled, master=master), "pil"

    import tkinter as tk

    photo = tk.PhotoImage(master=master, file=str(path))
    sx = max(1, int(round(photo.width() / float(size))))
    sy = max(1, int(round(photo.height() / float(size))))
    return photo.subsample(sx, sy), "tk"


class IconCache:
    """每张图只缩放一次；dict 持有 PhotoImage，防止被 Tk 回收。

    键是 ``("merchant", merchant_id)`` / ``("good", good_id)``。
    商人头像优先读 ``merchants_face/``（裁好的脸），没有再退回 ``merchants/``
    （整张 88×68 立绘）；两条路径都找不到的图也记进 `_missing`，避免每次
    重绘都去摸磁盘。
    """

    def __init__(self, master, icon_dir=None, portrait_dir=None,
                 face_dir=None, size=ICON_SIZE, use_pil=None):
        self.master = master
        self.icon_dir = Path(icon_dir) if icon_dir else ICON_DIR
        self.portrait_dir = Path(portrait_dir) if portrait_dir else PORTRAIT_DIR
        self.face_dir = Path(face_dir) if face_dir else FACE_DIR
        self.size = size
        self._pil = (None, None) if use_pil is False else _pil_modules()
        self._images = {}
        self._missing = set()
        self.hits = 0
        self.misses = 0
        self.backends = set()
        self.sizes = {}

    def directories(self, kind):
        """按优先级列出某个 kind 的图片目录（商人：脸 -> 整张立绘）。"""
        if kind == "merchant":
            return [self.face_dir, self.portrait_dir]
        return [self.icon_dir]

    def path_for(self, kind, key):
        """返回第一张存在的图路径；face 缺失时自动退回 ``merchants/``。"""
        if not _valid_key(key):
            return None
        for directory in self.directories(kind):
            path = Path(directory) / (key + ".png")
            if path.is_file():
                return path
        return None

    def get(self, kind, key):
        if not _valid_key(key):
            return None
        cache_key = (kind, key)
        if cache_key in self._images:
            self.hits += 1
            return self._images[cache_key]
        if cache_key in self._missing:
            return None

        self.misses += 1
        path = self.path_for(kind, key)
        if path is None:
            self._missing.add(cache_key)
            return None
        try:
            photo, backend = _load_photo(self.master, path, self.size, self._pil)
        except Exception:
            self._missing.add(cache_key)
            return None
        self._images[cache_key] = photo
        self.backends.add(backend)
        self.sizes[cache_key] = (photo.width(), photo.height())
        return photo

    def __len__(self):
        return len(self._images)

    def clear(self):
        self._images.clear()
        self._missing.clear()
        self.hits = 0
        self.misses = 0
        self.backends.clear()
        self.sizes.clear()


def fixed_merchants():
    """固定商人清单：来自 ``merchant_maps.json``，按线路 + 序号固定排序。"""
    try:
        maps = shop.load_merchant_maps()
    except Exception:
        maps = {}
    return _fixed_merchant_entries(maps)


def tier_color(good_id):
    """按商品档位取颜色；未知档位用正文色。"""
    try:
        tier = shop.load_goods().get(good_id, {}).get("tier", "")
    except Exception:
        tier = ""
    return TIER_COLORS.get(tier, COLOR_ROW)


def _goods_slot(good, side):
    good_id = good.get("id") or ""
    return {"good_id": good_id, "name": good.get("name") or good_id, "side": side}


def _fixed_goods_slots(merchant_id, goods=None):
    """这个商人固定的 8 个商品槽位：先卖后收，均按 goods.json 的文件顺序。

    卖：``goods[].seller == merchant_id``（2 普通 + 可能 1 波动）；
    收：``goods[].buyers`` 包含 ``merchant_id``，取文件顺序前 4 个普通回收货。
    槽位不足 8 个时补空位（价格显示「—」），所以坐标永远固定。
    """
    goods = shop.load_goods() if goods is None else goods
    sells, buys = [], []
    for good in (goods or {}).values():
        if isinstance(good, dict) and good.get("seller") == merchant_id:
            sells.append(good)
    for good in (goods or {}).values():
        if isinstance(good, dict) and merchant_id in (good.get("buyers") or []):
            buys.append(good)

    def rank(good):
        return TIER_RANK.get(good.get("tier") or "", 1)   # 未标档位按二类处理，稳住文件顺序

    slots = []
    # 档位顺序固定：紫（一类）→ 橙（二类）→ 绿（波动）；同档位按文件顺序
    for good in sorted(sells, key=rank)[:SELL_ROWS]:
        slots.append(_goods_slot(good, "sell"))
    for good in sorted(buys, key=rank)[:BUY_ROWS]:
        slots.append(_goods_slot(good, "buy"))
    while len(slots) < GOODS_SLOTS:
        slots.append({"good_id": "", "name": "", "side": ""})
    return slots


def _price_lookup(rows):
    """(good_id, side) / (名字, side) -> 价格；只收正数。"""
    prices = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        try:
            price = int(row.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        side = row.get("side") or ""
        good_id = row.get("good_id") or ""
        name = row.get("good") or ""
        if good_id:
            prices[(good_id, side)] = price
        if name:
            prices[("name", name, side)] = price
    return prices


def _slot_price(slot, prices):
    price = prices.get((slot.get("good_id") or "", slot.get("side") or ""))
    if price is None:
        price = prices.get(("name", slot.get("name") or "", slot.get("side") or ""))
    return price


def _block_height(_entry=None):
    """每个商人固定同高（标题 + 8 个商品槽位），位置不随数据变化。"""
    return HEAD_H + BUY_ROWS * ROW_H + BLOCK_GAP


def _split_board(entries):
    """列优先分配：左列先排，累计高度达到总高度一半就换右列。

    每个商人高度相同，所以 15 个固定分成左 8、右 7；顺序固定 -> 位置固定。
    """
    if len(entries) <= 1:
        return len(entries)
    heights = [_block_height(entry) for entry in entries]
    half = sum(heights) / 2.0
    accumulated = 0
    for index, height in enumerate(heights[:-1], start=1):
        accumulated += height
        if accumulated >= half:
            return index
    return len(entries) - 1


def _merchant_label(entry):
    return f"{entry.get('merchant') or '?'}@{entry.get('map') or '?'}"


def _remaining(entry, now):
    try:
        return float(entry.get("until", 0)) - now
    except (TypeError, ValueError):
        return 0.0


def _is_observed(entry):
    observed = entry.get("observed")
    if observed is None:
        return "until" in entry
    return bool(observed)


def _merge_fixed_entries(board, fixed):
    """把观察数据并进固定清单；没观察的商人也保留空条目占住位置。"""
    map_to_id = {entry["map"]: entry["merchant_id"] for entry in fixed}
    incoming = {}
    for entry in board or []:
        if not isinstance(entry, dict):
            continue
        merchant_id = entry.get("merchant_id") or ""
        if not merchant_id:
            merchant_id = map_to_id.get(entry.get("map", ""), "")
        if not merchant_id:
            continue
        incoming[merchant_id] = entry

    merged = []
    for base in fixed:
        entry = dict(base)
        entry.update({"until": 0.0, "observed": False, "rows": []})
        observation = incoming.get(base["merchant_id"])
        if observation is not None:
            entry["observed"] = _is_observed(observation)
            entry["until"] = observation.get("until", 0.0) or 0.0
            entry["rows"] = [row for row in observation.get("rows", []) or []
                             if isinstance(row, dict)]
        merged.append(entry)
    return merged


def _fallback_entries(board):
    """merchant_maps.json 读不到时的兜底：只画带名字 + merchant_id 的条目。"""
    entries = []
    seen = set()
    for entry in board or []:
        if not isinstance(entry, dict) or not entry.get("merchant"):
            continue
        merchant_id = entry.get("merchant_id") or ""
        if not merchant_id or merchant_id in seen:
            continue
        seen.add(merchant_id)
        merged = dict(entry)
        merged["observed"] = _is_observed(entry)
        merged["until"] = entry.get("until", 0.0) or 0.0
        merged["rows"] = [row for row in entry.get("rows", []) or []
                          if isinstance(row, dict)]
        entries.append(merged)
    entries.sort(key=lambda item: _merchant_sort_key(item.get("merchant_id")))
    return entries


def layout_board(board, width, now=None):
    """纯计算看板布局（不碰 Tk），返回 :class:`BoardLayout`。

    - 固定 15 个商人总是全部渲染，按 ``merchant_id`` 线路 + 序号排序；
    - 商人两列（左列 8、右列 7；窄窗口退回一列）；
    - 每个商人固定 2×4 = 8 个商品槽位（先卖后收），坐标与数据无关；
    - 没有观察记录：标题正常、倒计时「未看過」、价格「—」；
    - 倒计时在这里现算（``until - now``），颜色仍走 :func:`status_color`；
    - ``until`` 是墙钟（``time.time()``），所以 ``now`` 缺省也用墙钟。
    """
    if now is None:
        now = time.time()
    try:
        width = int(width)
    except (TypeError, ValueError):
        width = DEFAULT_BOARD_W
    width = max(width, 1)

    fixed = fixed_merchants()
    entries = _merge_fixed_entries(board, fixed) if fixed else _fallback_entries(board)
    if not entries:
        return BoardLayout(
            width=width, height=40, columns=0, column_width=width,
            items=[BoardItem(kind="placeholder", x=width // 2, y=12,
                             w=width, h=40, text="（打开商人界面后显示）",
                             color=COLOR_GRAY, anchor="n")],
        )

    try:
        goods = shop.load_goods()
    except Exception:
        goods = {}

    content = max(width - 2 * BOARD_PAD, 1)
    # 商人列数：宽度够就三列（15 个商人正好 5/5/5，顺序固定，位置永远不变）
    columns = 3 if content >= 3 * MIN_MERCHANT_COL + 2 * COLUMN_GAP else (
        2 if content >= 2 * MIN_MERCHANT_COL + COLUMN_GAP else 1)
    column_width = (content - (columns - 1) * COLUMN_GAP) // columns
    # 固定切分：不按高度均衡，避免数据变化导致商人位置跳动
    per_column = -(-len(entries) // columns)
    split = per_column
    chunks = [entries[i * per_column:(i + 1) * per_column] for i in range(columns)]

    items = []
    bottom = BOARD_PAD
    for column_index, chunk in enumerate(chunks):
        column_x = BOARD_PAD + column_index * (column_width + COLUMN_GAP)
        y = BOARD_PAD
        for entry in chunk:
            rows = list(entry.get("rows") or [])
            observed = _is_observed(entry)
            left = _remaining(entry, now) if observed else 0.0
            # 「未看过」和「已过期」对玩家是同一件事：这份价格不能用。
            # 统一显示「已過期」，不再多一个状态。
            expired = (not observed) or left <= 0
            color = COLOR_ROW if not observed else status_color(left)
            suffix = EXPIRED_TEXT if expired else f"剩 {format_duration(left)}"
            suffix_color = COLOR_UNSEEN if not observed else color
            items.append(BoardItem(
                kind="merchant", x=column_x, y=y, w=column_width, h=HEAD_H,
                owner=entry.get("merchant") or "",
                text=_merchant_label(entry),
                suffix=suffix, color=color, suffix_color=suffix_color,
                icon_kind="merchant" if entry.get("merchant_id") else "",
                icon_key=entry.get("merchant_id") or ""))

            slots = _fixed_goods_slots(entry.get("merchant_id") or "", goods)
            # 过期观察一律不显示旧价格；只有未过期且这次确实有该商品行才显示数字
            prices = _price_lookup(rows) if not expired else {}
            goods_width = max(1, (column_width - ROW_INDENT) // GOODS_COLUMNS)
            for index, slot in enumerate(slots):
                # 列由方向决定：左列永远是他卖的，右列永远是他收的。
                # （按序号切列会错位：卖只有 3 行时，第 1 个收会被挤进左列。）
                side_of = slot.get("side") or ""
                column = 0 if side_of == "sell" else 1
                if column == 0:
                    line = slots[:index].count(slot) if False else sum(
                        1 for s in slots[:index] if (s.get("side") or "") == "sell")
                else:
                    line = sum(1 for s in slots[:index]
                               if (s.get("side") or "") == "buy")
                item_x = column_x + ROW_INDENT + column * goods_width
                item_y = y + HEAD_H + line * ROW_H
                name_x = item_x + ICON_SIZE + ICON_GAP
                price_x = item_x + goods_width - PRICE_RIGHT_OFFSET
                label_x = max(name_x + NAME_MIN_GAP,
                              item_x + goods_width - LABEL_RIGHT_OFFSET)
                if label_x >= price_x:
                    label_x = max(name_x, price_x - NAME_MIN_GAP)
                if slot.get("good_id"):
                    side = slot.get("side") or ""
                    price = _slot_price(slot, prices)
                    # 只有真实有效的价格才用买卖色；「—」用浅灰
                    label_color = COLOR_ROW if price is not None else COLOR_GRAY
                    items.append(BoardItem(
                        kind="good", x=item_x, y=item_y, w=goods_width, h=ROW_H,
                        owner=entry.get("merchant") or "",
                        text=slot.get("name") or slot.get("good_id") or "?",
                        color=tier_color(slot.get("good_id") or ""),
                        icon_kind="good", icon_key=slot.get("good_id") or "",
                        good_id=slot.get("good_id") or "", side=side, slot=index,
                        label="卖" if side == "sell" else "收",
                        price_text=PRICE_EMPTY if price is None else str(price),
                        name_x=name_x, label_x=label_x, price_x=price_x,
                        label_color=label_color))
                # 空槽位留白：不画「—」，它在两列布局里只是噪点

            y += _block_height(entry)
        bottom = max(bottom, y)

    return BoardLayout(width=width, height=max(bottom, 1), columns=columns,
                       column_width=column_width, split=split, items=items)


def draw_board(canvas, board, now=None, icons=None, width=None):
    """把 `State.board` 画到 Canvas 上，返回画布内容高度（像素）。

    - 布局由 :func:`layout_board` 纯计算；倒计时在这里现算（``until - now``），
      ``until`` 是墙钟，所以 ``now`` 缺省也用 ``time.time()``；
    - `icons` 必须是调用方持有的 :class:`IconCache`（PhotoImage 生命周期）；
    - 商品名字左对齐、买卖标签固定 x、价格右对齐，不靠空格补位、不用等宽字体。
    """
    if now is None:
        now = time.time()
    if width is None or width <= 1:
        try:
            width = canvas.winfo_width()
        except Exception:
            width = 1
        if width <= 1:
            width = DEFAULT_BOARD_W

    layout = layout_board(board, width, now=now)

    canvas.delete("all")
    for item in layout.items:
        if item.kind == "placeholder":
            canvas.create_text(item.x, item.y, text=item.text,
                               anchor=item.anchor, fill=item.color,
                               font=ROW_FONT)
            continue

        if item.kind == "good":
            center_y = item.y + item.h // 2
            if item.good_id:
                image = icons.get("good", item.good_id) if icons is not None else None
                if image is not None:
                    canvas.create_image(item.x, item.y + (item.h - ICON_SIZE) // 2,
                                        image=image, anchor="nw")
                canvas.create_text(item.name_x, center_y, text=item.text,
                                   anchor="w", fill=item.color, font=ROW_FONT)
                canvas.create_text(item.label_x, center_y, text=item.label,
                                   anchor="w", fill=item.label_color, font=ROW_FONT)
                canvas.create_text(item.price_x, center_y, text=item.price_text,
                                   anchor="e", fill=item.label_color, font=ROW_FONT)
            else:
                # 固定但暂时没有商品的空槽位：在同一个位置显示「—」
                canvas.create_text(item.name_x, center_y, text=item.text,
                                   anchor="w", fill=item.color, font=ROW_FONT)
            continue

        image = None
        if icons is not None and item.icon_key:
            image = icons.get(item.icon_kind, item.icon_key)
        text_x = item.x
        if image is not None:
            canvas.create_image(item.x, item.y + (item.h - ICON_SIZE) // 2,
                                image=image, anchor="nw")
            text_x += ICON_SIZE + ICON_GAP

        canvas.create_text(text_x, item.y + item.h // 2, text=item.text,
                           anchor="w", fill=item.color, font=HEAD_FONT)
        if item.suffix:
            # 倒计时右对齐，长商人名也不会把它顶出列外
            canvas.create_text(item.x + item.w, item.y + item.h // 2,
                               text=item.suffix, anchor="e",
                               fill=item.suffix_color or item.color,
                               font=HEAD_FONT)

    canvas.configure(scrollregion=(0, 0, layout.width, layout.height))
    return layout.height


# ---------------------------------------------------------------------- GUI
def apply_icon(root):
    """窗口/任务栏图标：跑商小地图里那个图标，比任何自造的图标都有代表性。"""
    import tkinter as tk
    path = ASSETS_DIR / "app_icon.png"
    try:
        image = tk.PhotoImage(file=str(path))
        root.iconphoto(True, image)
        root._icon_ref = image        # 保持引用，否则会被回收
    except Exception:
        pass
    try:
        if ICON_PATH.exists():
            root.iconbitmap(default=str(ICON_PATH))
    except Exception:
        pass


def run_gui(interval=0.1):
    import tkinter as tk

    controller = Controller()
    root = tk.Tk()
    root.title("小助手")
    apply_icon(root)
    root.geometry(f"{WINDOW_W}x{WINDOW_H}")

    # 主区分左右：左边商人看板，右边建议列（整窗高）。
    # 建议列在右侧，因为玩家主屏在看板右边，UI 右缘先进入视线。
    main_frame = tk.Frame(root)
    main_frame.pack(fill="both", expand=True)

    board_column = tk.Frame(main_frame)
    board_column.pack(side="left", fill="both", expand=True)
    advice_column = tk.Frame(main_frame, width=ADVICE_COL_W)
    advice_column.pack(side="right", fill="y")
    advice_column.pack_propagate(False)

    tk.Label(board_column, text="商人看板（货 + 倒计时）", anchor="w",
             font=("Microsoft YaHei", 10, "bold")).pack(fill="x")
    board_frame = tk.Frame(board_column)
    board_frame.pack(fill="both", expand=True, padx=4)

    tk.Label(advice_column, text="当前建议", anchor="w",
             font=("Microsoft YaHei", 10, "bold")).pack(fill="x")
    advice_box = tk.Text(advice_column, font=("Microsoft YaHei", 9), wrap="none",
                         height=ADVICE_ROWS, width=1)
    advice_box.pack(fill="both", expand=True, padx=4)
    canvas = tk.Canvas(board_frame, bg="white", highlightthickness=0, bd=0)
    scrollbar = tk.Scrollbar(board_frame, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    # 图标缓存由 paint 闭包长期持有；每张图只缩放一次
    icons = IconCache(canvas)

    def on_wheel(event):
        # 内容一屏放得下就不要滚：否则 scrollregion 只有一屏高，
        # 滚动仍会把整块内容顶上去，看起来像"没滚动条却会动"。
        top, bottom = canvas.yview()
        if top <= 0.0 and bottom >= 1.0:
            return
        step = -1 if getattr(event, "delta", 0) > 0 else 1
        canvas.yview_scroll(step * 2, "units")

    canvas.bind("<MouseWheel>", on_wheel)

    status = tk.Label(root, text="", anchor="w", font=("Microsoft YaHei", 8), fg="#666")
    status.pack(fill="x")

    worker = _Worker(_grabber(), controller, interval=interval)
    painted = {"version": -1, "at": 0.0}
    shown = {"state": None}

    def paint(state):
        # 竖排：每组（同一商店/同一商品）之间空一行，空间足够就不折叠
        blocks = list(state.blocks or [["（打开商人界面后显示）"]])
        lines = []
        for block in blocks:
            if lines:
                lines.append("")
            lines.extend(block)
        text = "\n".join(lines)
        if advice_box.get("1.0", "end-1c") != text:   # 内容没变就别重写，否则选中会被清掉
            advice_box.delete("1.0", "end")
            advice_box.insert("end", text)
        content_h = draw_board(canvas, state.board, icons=icons,
                               width=canvas.winfo_width())
        # 只有内容真的超出视口才放出滚动条
        try:
            need = content_h > canvas.winfo_height() + 1
            if need and not scrollbar.winfo_ismapped():
                scrollbar.pack(side="right", fill="y")
            elif not need and scrollbar.winfo_ismapped():
                scrollbar.pack_forget()
        except Exception:
            pass
        status.config(text=f"{state.map or '(未知地图)'}　{state.note}")
        shown["state"] = state

    def on_resize(event):
        if shown["state"] is not None:
            draw_board(canvas, shown["state"].board, icons=icons, width=event.width)

    canvas.bind("<Configure>", on_resize)

    def tick():
        # 只用来看"该不该重画"（本进程内的节流），不参与倒计时/落盘。
        now = time.monotonic()
        try:
            state = worker.latest()
        except Exception as exc:
            status.config(text=f"读取失败：{exc}")
            root.after(int(interval * 1000), tick)
            return
        if state is None:
            root.after(int(interval * 1000), tick)
            return
        # 数据变了立刻画；否则每 REPAINT_EVERY 秒重画一次，让倒计时走字
        if state.version != painted["version"] or now - painted["at"] >= REPAINT_EVERY:
            paint(state)
            painted["version"] = state.version
            painted["at"] = now
        root.after(int(interval * 1000), tick)

    root.after(0, tick)
    root.mainloop()


class _Worker:
    """后台线程：抓帧 + 全部识别/计算，UI 线程只取结果去画。"""

    def __init__(self, grab, controller, interval=0.1):
        import threading

        self._grab = grab
        self._controller = controller
        self._interval = interval
        self._lock = threading.Lock()
        self._state = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                frame = self._grab()
                if frame is not None:
                    state = self._controller.update(frame)
                    with self._lock:
                        self._state = state
            except Exception:
                pass
            self._stop.wait(self._interval)

    def latest(self):
        with self._lock:
            return self._state

    def stop(self):
        self._stop.set()


class _Capture:
    """后台线程抓帧：UI 线程只取最新一帧，拖动窗口时不会被抓帧卡住。"""

    def __init__(self, grab, interval=0.1):
        import queue
        import threading

        self._grab = grab
        self._interval = interval
        self._queue = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                frame = self._grab()
            except Exception:
                frame = None
            if frame is not None:
                try:
                    self._queue.get_nowait()      # 丢掉旧帧，永远只处理最新的
                except Exception:
                    pass
                try:
                    self._queue.put_nowait(frame)
                except Exception:
                    pass
            self._stop.wait(self._interval)

    def latest(self):
        try:
            return self._queue.get_nowait()
        except Exception:
            return None

    def stop(self):
        self._stop.set()


def _grabber():
    import mss
    import win32gui

    best = None

    def callback(hwnd, _):
        nonlocal best
        if not win32gui.IsWindowVisible(hwnd) or win32gui.GetWindowText(hwnd) != "MapleStory":
            return
        rect = win32gui.GetWindowRect(hwnd)
        area = (rect[2] - rect[0]) * (rect[3] - rect[1])
        if best is None or area > best[0]:
            best = (area, hwnd)

    win32gui.EnumWindows(callback, None)
    if best is None:
        raise SystemExit("找不到 MapleStory 窗口")
    hwnd = best[1]
    ox, oy = win32gui.ClientToScreen(hwnd, (0, 0))
    cw, ch = win32gui.GetClientRect(hwnd)[2:]

    def grab():
        with mss.mss() as sct:
            return __import__("numpy").array(
                sct.grab({"left": ox, "top": oy, "width": cw, "height": ch}))[:, :, :3].copy()

    return grab


if __name__ == "__main__":
    run_gui()
