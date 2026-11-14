"""跑商助手 GUI：独立小窗，三块面板，分批刷新。

刷新节奏（详见 TRADE_DESIGN.md 第 15 节）：

    抓帧 / 地图跟踪     每 100ms
    读购物界面          0.4s（打开瞬间立刻读一次）
    读货舱              1.0s
    看板数据重建        2.0s
    窗口重绘            0.25s（倒计时在绘制时现算，所以每秒都在走）

逻辑与界面分离：`Controller` 只处理画面 -> 状态，测试不需要显示环境。
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

from . import advice as advice_module
from . import ledger as ledger_module
from . import mapwatch
from . import shop
from . import trade

SHOP_EVERY = 0.4
CARGO_EVERY = 1.0
REPAINT_EVERY = 0.25
BOARD_EVERY = 2.0

ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "data" / "trade" / "icons"
PORTRAIT_DIR = ROOT / "data" / "trade" / "merchants"

#: 窗口尺寸：宽度 380 -> 760（加倍），高度 620 -> 930（×1.5）。
#: 多出来的高度全部给商人看板，当前建议仍是固定 8 行。
WINDOW_W = 760
WINDOW_H = 930
ADVICE_ROWS = 4
ADVICE_COLS = 88
#: 首帧 canvas 还没实际宽度时的兜底（760 窗口减去内边距和滚动条）
DEFAULT_BOARD_W = WINDOW_W - 24

#: 看板尺寸 / 间距（TRADE_DESIGN.md 15.2 / 15.3）
ICON_SIZE = 16
HEAD_H = 22
ROW_H = 20
BLOCK_GAP = 2
BOARD_PAD = 4
ROW_INDENT = 10
ICON_GAP = 4

#: 商人两列 + 每个商人固定 2×4 商品槽位（永久同样的位置）
COLUMN_GAP = 12          # 两个商人列之间的空隙
GOODS_COLUMNS = 2        # 商品固定两列
GOODS_ROWS = 4           # 商品固定四行
GOODS_SLOTS = GOODS_COLUMNS * GOODS_ROWS    # 每个商人固定 8 个槽位
MIN_MERCHANT_COL = 260   # 单列至少这么宽才排两列，窄窗口自动退回一列

#: 固定商人的线路顺序：kobi < dour < ore，再按 merchant_id 的数字序号
LINE_ORDER = {"kobi": 0, "dour": 1, "ore": 2}

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
class State:
    map: str = ""
    advice: list = field(default_factory=list)
    cargo: list = field(default_factory=list)
    board: list = field(default_factory=list)
    note: str = ""
    version: int = 0


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


def _merchant_sort_key(merchant_id):
    """``kobi_1`` -> (0, 1)，线路前缀优先、数字序号其次。"""
    prefix, _, suffix = str(merchant_id or "").partition("_")
    try:
        number = int(suffix)
    except (TypeError, ValueError):
        number = 10 ** 9
    return (LINE_ORDER.get(prefix, len(LINE_ORDER)), number, str(merchant_id or ""))


def _observed_at(observation):
    try:
        return float(observation.get("t", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _row_merge_key(row, index):
    """合并观察时的行标识：``(good_id, side)``。

    老记录可能没有 ``good_id``，退化为「商品名 + 方向」；连名字都没有的
    行无法归类，用 ``index`` 让它逐条保留（和以前一样不做合并）。
    """
    good_id = row.get("good_id") or ""
    side = row.get("side") or ""
    if good_id:
        return ("id", good_id, side)
    name = row.get("good") or ""
    if name:
        return ("name", name, side)
    return ("raw", index)


def _merge_merchant_observations(observations, now, valid_until):
    """把同一个商人的多条观察合并成一份 (until, rows)。

    一次滚动只看得见当时那几行，所以每条观察都是**部分**数据；只取最新一条
    会把之前的行丢掉（先看到"卖"、往下滚看到"收"，卖价就变成「—」）。

    - 过期的观察整条丢掉，不贡献任何行；
    - 未过期的观察按 ``t`` 从旧到新合并，``(good_id, side)`` 相同就取 ``t`` 更大的价格；
    - ``until`` 取该商人所有观察里最大的 ``valid_until``：同一个商人的刷新
      倒计时相同，所以它就是最新那条有效观察的 until；并且只要有一条没过期
      就 ``until > now``，全都过期才 ``until <= now``（界面显示「已過期」）。
    """
    until = 0.0
    merged = {}
    ordered = sorted((item for item in observations if isinstance(item, dict)),
                     key=_observed_at)
    for observation in ordered:
        try:
            expiry = float(valid_until(observation))
        except Exception:
            expiry = 0.0
        until = max(until, expiry)
        if expiry <= now:
            continue                       # 过期的整条丢掉
        observed_at = _observed_at(observation)
        for index, row in enumerate(observation.get("rows", []) or []):
            if not isinstance(row, dict):
                continue
            key = _row_merge_key(row, index)
            previous = merged.get(key)
            if previous is None or observed_at > previous[0]:
                merged[key] = (observed_at, dict(row))
    return until, [row for _, row in merged.values()]


def _fixed_merchant_entries(maps):
    """把 ``merchant_maps.json`` 的 地图 -> 商人 变成固定顺序的商人清单。"""
    entries = []
    seen = set()
    for map_name, info in (maps or {}).items():
        if not isinstance(info, dict):
            continue
        merchant_id = info.get("merchant_id") or ""
        if not merchant_id or merchant_id in seen:
            continue
        seen.add(merchant_id)
        entries.append({
            "merchant_id": merchant_id,
            # 游戏内是繁体名，优先用它；没有才退回文档简体名
            "merchant": info.get("game_name") or info.get("merchant") or merchant_id,
            "game_name": info.get("game_name") or "",
            "doc_name": info.get("merchant") or "",
            "map": map_name,
        })
    entries.sort(key=lambda entry: _merchant_sort_key(entry["merchant_id"]))
    return entries


class Controller:
    def __init__(self, watcher=None, ledger=None, travel=None, now=None):
        self.watcher = watcher or mapwatch.MapWatcher()
        self.ledger = ledger or ledger_module.Ledger()
        self.travel = travel or advice_module.MapTravel()
        self.state = State()
        self._open = False
        self._shop_at = 0.0
        self._cargo_at = 0.0
        self._board_at = 0.0
        self._merged = {}
        self._merchant_maps = None
        self._fixed_cache = None

    # ------------------------------------------------------------------
    def current_map(self):
        previous = getattr(self.watcher, "last_map_obs", None)
        return getattr(previous, "map_id", "") or ""

    def update(self, frame, now=None):
        now = time.monotonic() if now is None else float(now)
        try:
            self.watcher.step(frame, now=now)
        except Exception:
            pass
        self.state.map = self.current_map()

        opened = _safe(trade.find_shop_window, frame, default=False)
        if opened:
            if not self._open or now - self._shop_at >= SHOP_EVERY:
                self._read_shop(frame, now)
                self._shop_at = now
            self._open = True
        else:
            self._open = False
            self._merged = {}
            if _safe(trade.find_cargo_window, frame, default=False):
                if now - self._cargo_at >= CARGO_EVERY:
                    self._read_cargo(frame, now)
                    self._cargo_at = now

        if now - self._board_at >= BOARD_EVERY:
            self._read_board(now)
            self._board_at = now
        return self.state

    # ------------------------------------------------------------------
    def _read_shop(self, frame, now):
        try:
            visit = shop.read_visit(frame, self.state.map)
        except Exception as exc:
            self.state.note = f"读商店失败：{exc}"
            return
        # 滚动合并：窗口一直开着时，每次只看得见当时那几行，所以要把多次
        # 读取累积起来；条目带读取时刻，超过该商人刷新窗口的旧价格丢掉
        # （商人刷新后旧价格不能继续留在合并结果里）。
        for row in visit.rows:
            self._merged[(row.good_id, row.side)] = (row, now)
        window = float(visit.refresh_in or 300)
        cutoff = now - window
        self._merged = {key: value for key, value in self._merged.items()
                        if value[1] >= cutoff}
        visit.rows = [row for row, _t in self._merged.values()]
        # 先合并再记录：observations.jsonl 里每条都是当前已知的完整清单，
        # 同一商人的最新一条就能代表全部（看板侧的多条合并只兜老数据）。
        try:
            self.ledger.record(visit, now=now)
        except Exception:
            pass
        lines = []
        try:
            items = advice_module.suggest(visit, self.ledger, self.travel, now=now)
            lines = advice_module.format_suggestions(items)
            if not items:
                explore = advice_module.explore_plan(self.ledger, self.travel,
                                                     now=now, current_map=self.state.map)
                for item in explore:
                    lines.append(f"去看看 {item['merchant']}({item['map']}) "
                                 f"{item['hops']} 张图")
        except Exception as exc:
            lines = [f"建议计算失败：{exc}"]
        self.state.advice = lines
        self.state.version += 1

    def _read_cargo(self, frame, now):
        try:
            held = shop.read_cargo_items(frame)
        except Exception as exc:
            self.state.note = f"读货舱失败：{exc}"
            return
        plan = []
        try:
            plan = advice_module.sell_plan(held, self.ledger, self.travel,
                                           now=now, current_map=self.state.map)
        except Exception:
            plan = []
        lines = []
        for item in plan:
            hops = item.get("hops")
            lines.append(f"{item['good']} → {item['merchant']}({item['map']}) "
                         f"@{item['price']}（{hops} 张图）")
        self.state.cargo = lines or (["（没有可信收购价，先去附近看看）"] if held else [])
        self.state.version += 1

    def _read_board(self, now):
        """固定顺序的 15 个商人；随机商人和未知 merchant_id 一律丢弃。

        即使某个商人没有任何观察记录也保留一条（``observed=False``），
        这样布局永远拿到同样数量的条目，位置不会因为新数据而变。

        每个商人把**所有未过期**的观察合并起来（见
        :func:`_merge_merchant_observations`）：滚动后新记录的观察只含当时
        可见的几行，只取最新一条会丢掉之前的「卖」行。
        """
        try:
            observations = self.ledger.load()
        except Exception:
            observations = []
        grouped = {}
        for observation in observations:
            if not isinstance(observation, dict) or not self._is_fixed_merchant(observation):
                continue
            merchant_id = (observation.get("merchant_id")
                           or self._merchant_id_for(observation.get("map", "")))
            if not merchant_id:
                continue
            grouped.setdefault(merchant_id, []).append(observation)

        board = []
        for fixed in self._fixed_merchants():
            records = grouped.get(fixed["merchant_id"]) or []
            entry = {
                "merchant": fixed["merchant"],
                "merchant_id": fixed["merchant_id"],
                "map": fixed["map"],
                "until": 0.0,
                "observed": bool(records),      # 有过记录就算看过，过期由 until 判断
                "rows": [],
            }
            if records:
                until, rows = _merge_merchant_observations(
                    records, now, self.ledger.valid_until)
                entry["until"] = until
                entry["rows"] = rows
            board.append(entry)
        self.state.board = board
        self.state.version += 1

    def _fixed_merchants(self):
        if self._fixed_cache is None:
            self._fixed_cache = _fixed_merchant_entries(self._ensure_merchant_maps())
        return self._fixed_cache

    def _is_fixed_merchant(self, observation):
        """固定商人的判定：merchant 非空，且 merchant_id 在 merchant_maps.json 里。

        随机商人没有 merchant / merchant_id（老记录甚至只剩地图名），一律过滤。
        读不到 merchant_maps.json 时退化为只要求两个字段非空，避免整个看板空掉。
        """
        if not isinstance(observation, dict) or not observation.get("merchant"):
            return False
        merchant_id = (observation.get("merchant_id")
                       or self._merchant_id_for(observation.get("map", "")))
        if not merchant_id:
            return False
        known = self._known_merchant_ids()
        return not known or merchant_id in known

    def _ensure_merchant_maps(self):
        if self._merchant_maps is None:
            try:
                self._merchant_maps = shop.load_merchant_maps()
            except Exception:
                self._merchant_maps = {}
        return self._merchant_maps

    def _known_merchant_ids(self):
        return {entry.get("merchant_id")
                for entry in self._ensure_merchant_maps().values()
                if isinstance(entry, dict) and entry.get("merchant_id")}

    def _merchant_id_for(self, map_name):
        """老记录没存 merchant_id 时按地图反查（merchant_maps.json）。"""
        if not map_name:
            return ""
        info = self._ensure_merchant_maps().get(map_name)
        return info.get("merchant_id", "") if isinstance(info, dict) else ""


def _safe(function, frame, default=None):
    try:
        return function(frame)
    except Exception:
        return default


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

    PIL 可用时走 LANCZOS（商品 63×63、头像 88×68 都压到 16×16）；
    否则用 PhotoImage.subsample，按两轴各自最接近的整数倍缩小。
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
    找不到的图也记进 `_missing`，避免每次重绘都去摸磁盘。
    """

    def __init__(self, master, icon_dir=None, portrait_dir=None,
                 size=ICON_SIZE, use_pil=None):
        self.master = master
        self.icon_dir = Path(icon_dir) if icon_dir else ICON_DIR
        self.portrait_dir = Path(portrait_dir) if portrait_dir else PORTRAIT_DIR
        self.size = size
        self._pil = (None, None) if use_pil is False else _pil_modules()
        self._images = {}
        self._missing = set()
        self.hits = 0
        self.misses = 0
        self.backends = set()
        self.sizes = {}

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
        directory = self.portrait_dir if kind == "merchant" else self.icon_dir
        path = directory / (key + ".png")
        if not path.is_file():
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

    slots = []
    for good in sells[:GOODS_ROWS]:
        slots.append(_goods_slot(good, "sell"))
    for good in buys[:GOODS_ROWS]:
        slots.append(_goods_slot(good, "buy"))
    slots = slots[:GOODS_SLOTS]
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
    return HEAD_H + GOODS_ROWS * ROW_H + BLOCK_GAP


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
    - 倒计时在这里现算（``until - now``），颜色仍走 :func:`status_color`。
    """
    if now is None:
        now = time.monotonic()
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
    if content >= 2 * MIN_MERCHANT_COL + COLUMN_GAP:
        columns = 2
        column_width = (content - COLUMN_GAP) // 2
        split = _split_board(entries)
        chunks = [entries[:split], entries[split:]]
    else:
        columns = 1
        column_width = content
        split = len(entries)
        chunks = [entries]

    items = []
    bottom = BOARD_PAD
    for column_index, chunk in enumerate(chunks):
        column_x = BOARD_PAD + column_index * (column_width + COLUMN_GAP)
        y = BOARD_PAD
        for entry in chunk:
            rows = list(entry.get("rows") or [])
            observed = _is_observed(entry)
            left = _remaining(entry, now) if observed else 0.0
            expired = (not observed) or left <= 0
            if observed:
                color = status_color(left)
                suffix = EXPIRED_TEXT if expired else f"剩 {format_duration(left)}"
                suffix_color = color
            else:
                # 没有数据：标题正常显示，倒计时位置显示浅灰「未看過」
                color = COLOR_ROW
                suffix = UNSEEN_TEXT
                suffix_color = COLOR_UNSEEN
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
                column = index % GOODS_COLUMNS
                line = index // GOODS_COLUMNS
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
                    if price is None:
                        label_color = COLOR_GRAY
                    else:
                        label_color = COLOR_SELL if side == "sell" else COLOR_BUY
                    items.append(BoardItem(
                        kind="good", x=item_x, y=item_y, w=goods_width, h=ROW_H,
                        owner=entry.get("merchant") or "",
                        text=slot.get("name") or slot.get("good_id") or "?",
                        color=COLOR_ROW,
                        icon_kind="good", icon_key=slot.get("good_id") or "",
                        good_id=slot.get("good_id") or "", side=side, slot=index,
                        label="卖" if side == "sell" else "收",
                        price_text=PRICE_EMPTY if price is None else str(price),
                        name_x=name_x, label_x=label_x, price_x=price_x,
                        label_color=label_color))
                else:
                    items.append(BoardItem(
                        kind="good", x=item_x, y=item_y, w=goods_width, h=ROW_H,
                        owner=entry.get("merchant") or "",
                        text=PRICE_EMPTY, color=COLOR_GRAY,
                        slot=index, price_text=PRICE_EMPTY,
                        name_x=name_x, label_x=label_x, price_x=price_x,
                        label_color=COLOR_GRAY))

            y += _block_height(entry)
        bottom = max(bottom, y)

    return BoardLayout(width=width, height=max(bottom, 1), columns=columns,
                       column_width=column_width, split=split, items=items)


def draw_board(canvas, board, now=None, icons=None, width=None):
    """把 `State.board` 画到 Canvas 上，返回画布内容高度（像素）。

    - 布局由 :func:`layout_board` 纯计算；倒计时在这里现算（``until - now``）；
    - `icons` 必须是调用方持有的 :class:`IconCache`（PhotoImage 生命周期）；
    - 商品名字左对齐、买卖标签固定 x、价格右对齐，不靠空格补位、不用等宽字体。
    """
    if now is None:
        now = time.monotonic()
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
def run_gui(interval=0.1):
    import tkinter as tk

    controller = Controller()
    root = tk.Tk()
    root.title("小助手")
    root.geometry(f"{WINDOW_W}x{WINDOW_H}")

    tk.Label(root, text="当前建议", anchor="w", font=("Microsoft YaHei", 10, "bold")).pack(fill="x")
    # 8 行高度保持不变，宽度跟着窗口加宽
    advice_box = tk.Text(root, height=ADVICE_ROWS, width=ADVICE_COLS,
                         font=("Microsoft YaHei", 9))
    advice_box.pack(fill="x", padx=4)

    tk.Label(root, text="商人看板（货 + 倒计时）", anchor="w",
             font=("Microsoft YaHei", 10, "bold")).pack(fill="x")
    board_frame = tk.Frame(root)
    board_frame.pack(fill="both", expand=True, padx=4)
    canvas = tk.Canvas(board_frame, bg="white", highlightthickness=0, bd=0)
    scrollbar = tk.Scrollbar(board_frame, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    # 图标缓存由 paint 闭包长期持有；每张图只缩放一次
    icons = IconCache(canvas)

    def on_wheel(event):
        step = -1 if getattr(event, "delta", 0) > 0 else 1
        canvas.yview_scroll(step * 2, "units")

    canvas.bind("<MouseWheel>", on_wheel)

    status = tk.Label(root, text="", anchor="w", font=("Microsoft YaHei", 8), fg="#666")
    status.pack(fill="x")

    worker = _Worker(_grabber(), controller, interval=interval)
    painted = {"version": -1, "at": 0.0}
    shown = {"state": None}

    def paint(state):
        advice_text = "\n".join(state.advice) or "（打开商人界面后显示）"
        if advice_box.get("1.0", "end-1c") != advice_text:   # 内容没变就别重写，否则选中会被清掉
            advice_box.delete("1.0", "end")
            advice_box.insert("end", advice_text)
        draw_board(canvas, state.board, icons=icons, width=canvas.winfo_width())
        status.config(text=f"{state.map or '(未知地图)'}　{state.note}")
        shown["state"] = state

    def on_resize(event):
        if shown["state"] is not None:
            draw_board(canvas, shown["state"].board, icons=icons, width=event.width)

    canvas.bind("<Configure>", on_resize)

    def tick():
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
