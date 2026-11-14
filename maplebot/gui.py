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

- 商人条目排成 **两列**，列优先：左列先排，接近总高度一半后再换右列；
- 每个商人的商品 **每列最多 3 件**，按列排（4 件 -> 2×2，5~6 件 -> 2×3），
  所有商品都占位置，不截断；
- 只画固定商人；``merchant`` / ``merchant_id`` 为空的随机商人由 Controller 过滤掉，
  布局函数里也再挡一层。
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
ADVICE_ROWS = 8
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

#: 商人两列 + 每个商人的商品多列
COLUMN_GAP = 12          # 两个商人列之间的空隙
GOODS_PER_COLUMN = 3     # 商品每列最多 3 件
MIN_MERCHANT_COL = 260   # 单列至少这么宽才排两列，窄窗口自动退回一列

#: 倒计时颜色（15.5）：>60s 绿、≤60s 黄、已过期灰
COLOR_GREEN = "#2e7d32"
COLOR_YELLOW = "#f9a825"
COLOR_GRAY = "#9e9e9e"
COLOR_ROW = "#333333"

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
    text: str = ""
    suffix: str = ""             # 商人标题右侧的倒计时
    color: str = COLOR_ROW
    suffix_color: str = ""
    icon_kind: str = ""          # merchant | good | ""
    icon_key: str = ""
    anchor: str = "nw"


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
        try:
            self.ledger.record(visit, now=now)
        except Exception:
            pass
        for row in visit.rows:
            self._merged[(row.good_id, row.side)] = row.price
        if self._merged:
            visit.rows = [shop.Row(g, _name(g), side, price)
                          for (g, side), price in self._merged.items()]
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
        """只看固定商人；随机商人（merchant / merchant_id 为空）不进看板。"""
        board = []
        try:
            observations = self.ledger.load()
        except Exception:
            observations = []
        latest = {}
        for observation in observations:
            if not self._is_fixed_merchant(observation):
                continue
            key = observation.get("merchant")
            if not key:
                continue
            if key not in latest or observation.get("t", 0) > latest[key].get("t", 0):
                latest[key] = observation
        for key, observation in sorted(latest.items()):
            until = self.ledger.valid_until(observation)
            merchant_id = observation.get("merchant_id", "")
            if not merchant_id:
                merchant_id = self._merchant_id_for(observation.get("map", ""))
            board.append({"merchant": key, "merchant_id": merchant_id,
                          "map": observation.get("map", ""),
                          "until": until,
                          "rows": [dict(row) for row in observation.get("rows", []) or []
                                   if isinstance(row, dict)]})
        self.state.board = board
        self.state.version += 1

    def _is_fixed_merchant(self, observation):
        """固定商人的判定：merchant 非空，且 merchant_id 在 merchant_maps.json 里。

        随机商人没有 merchant / merchant_id（老记录甚至只剩地图名），一律过滤。
        读不到 merchant_maps.json 时退化为只要求两个字段非空，避免整个看板空掉。
        """
        if not observation.get("merchant"):
            return False
        merchant_id = observation.get("merchant_id", "")
        if not merchant_id:
            merchant_id = self._merchant_id_for(observation.get("map", ""))
        if not merchant_id:
            return False
        known = self._known_merchant_ids()
        return not known or merchant_id in known

    def _known_merchant_ids(self):
        if self._merchant_maps is None:
            try:
                self._merchant_maps = shop.load_merchant_maps()
            except Exception:
                self._merchant_maps = {}
        return {entry.get("merchant_id")
                for entry in self._merchant_maps.values()
                if isinstance(entry, dict) and entry.get("merchant_id")}

    def _merchant_id_for(self, map_name):
        """老记录没存 merchant_id 时按地图反查（merchant_maps.json）。"""
        if not map_name:
            return ""
        if self._merchant_maps is None:
            try:
                self._merchant_maps = shop.load_merchant_maps()
            except Exception:
                self._merchant_maps = {}
        return self._merchant_maps.get(map_name, {}).get("merchant_id", "")


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


def _goods_grid(count):
    """一个商人的商品网格：(列数, 每列行数)。

    每列最多 ``GOODS_PER_COLUMN`` 件；列数取够用的最小值，行数在各列间尽量均衡：
    4 件 -> 2×2，5 件 -> 2×3（最后一列 2 件），6 件 -> 2×3。
    """
    if count <= 0:
        return 1, 0
    columns = (count + GOODS_PER_COLUMN - 1) // GOODS_PER_COLUMN
    rows = (count + columns - 1) // columns
    return columns, rows


def _block_height(entry):
    _, rows = _goods_grid(len(entry.get("rows") or []))
    return HEAD_H + rows * ROW_H + BLOCK_GAP


def _split_board(entries):
    """列优先分配：左列先排，累计高度达到总高度一半就换右列。"""
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


def layout_board(board, width, now=None):
    """纯计算看板布局（不碰 Tk），返回 :class:`BoardLayout`。

    - 只保留有 ``merchant`` / ``merchant_id`` 的固定商人；随机商人直接跳过；
    - 商人条目排成两列（窗口太窄时退回一列），列优先：左列先排，接近总高度
      一半后再换右列；
    - 每个商人的商品每列最多 3 件，按列填（divmod 按每列行数），全部商品都占位置，
      不截断；
    - 倒计时在这里现算（``until - now``），颜色仍走 :func:`status_color`。
    """
    if now is None:
        now = time.monotonic()
    try:
        width = int(width)
    except (TypeError, ValueError):
        width = DEFAULT_BOARD_W
    width = max(width, 1)

    entries = [entry for entry in (board or [])
               if isinstance(entry, dict) and entry.get("merchant")
               and entry.get("merchant_id")]
    if not entries:
        return BoardLayout(
            width=width, height=40, columns=0, column_width=width,
            items=[BoardItem(kind="placeholder", x=width // 2, y=12,
                             w=width, h=40, text="（打开商人界面后显示）",
                             color=COLOR_GRAY, anchor="n")],
        )

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
            left = _remaining(entry, now)
            expired = left <= 0
            color = status_color(left)
            items.append(BoardItem(
                kind="merchant", x=column_x, y=y, w=column_width, h=HEAD_H,
                owner=entry.get("merchant") or "",
                text=_merchant_label(entry),
                suffix="已过期" if expired else f"剩 {int(left)}s",
                color=color, suffix_color=color,
                icon_kind="merchant" if entry.get("merchant_id") else "",
                icon_key=entry.get("merchant_id") or ""))

            count = len(rows)
            goods_columns, goods_rows = _goods_grid(count)
            goods_width = max(1, (column_width - ROW_INDENT) // goods_columns)
            for index, row in enumerate(rows):
                column, line = divmod(index, goods_rows)
                side = "卖" if row.get("side") == "sell" else "收"
                text = (f"{row.get('good') or row.get('good_id') or '?'} "
                        f"{side} {row.get('price', 0)}")
                items.append(BoardItem(
                    kind="good",
                    x=column_x + ROW_INDENT + column * goods_width,
                    y=y + HEAD_H + line * ROW_H,
                    w=goods_width, h=ROW_H,
                    owner=entry.get("merchant") or "",
                    text=text,
                    color=COLOR_GRAY if expired else COLOR_ROW,
                    icon_kind="good" if row.get("good_id") else "",
                    icon_key=row.get("good_id") or ""))

            y += HEAD_H + goods_rows * ROW_H + BLOCK_GAP
        bottom = max(bottom, y)

    return BoardLayout(width=width, height=max(bottom, 1), columns=columns,
                       column_width=column_width, split=split, items=items)


def draw_board(canvas, board, now=None, icons=None, width=None):
    """把 `State.board` 画到 Canvas 上，返回画布内容高度（像素）。

    - 布局由 :func:`layout_board` 纯计算；倒计时在这里现算（``until - now``）；
    - `icons` 必须是调用方持有的 :class:`IconCache`（PhotoImage 生命周期）；
    - 看板只画固定商人；没有可画的条目时显示一行占位提示。
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

        image = None
        if icons is not None and item.icon_key:
            image = icons.get(item.icon_kind, item.icon_key)
        text_x = item.x
        if image is not None:
            canvas.create_image(item.x, item.y + (item.h - ICON_SIZE) // 2,
                                image=image, anchor="nw")
            text_x += ICON_SIZE + ICON_GAP

        font = HEAD_FONT if item.kind == "merchant" else ROW_FONT
        canvas.create_text(text_x, item.y + item.h // 2, text=item.text,
                           anchor="w", fill=item.color, font=font)
        if item.kind == "merchant" and item.suffix:
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
        advice_box.delete("1.0", "end")
        advice_box.insert("end", "\n".join(state.advice) or "（打开商人界面后显示）")
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
