"""跑商会话：画面 -> 状态的全部逻辑，GUI / 控制台共用。

这里只做「读画面 + 算建议」，不碰 Tk、不打印。视图层（``gui`` / ``runtime``）
拿到 :class:`State` 后各自决定怎么显示：

- ``gui.Controller`` 是 :class:`TradeSession` 的薄壳，Tk 线程只画 ``State``；
- ``runtime.Runtime`` 每帧调用 :meth:`TradeSession.update`，再把 ``State``
  格式化成控制台文本行。

刷新节奏（详见 TRADE_DESIGN.md 第 15 节）：

    抓帧 / 地图跟踪     每 100ms（调用方决定）
    读购物界面          0.4s（打开瞬间立刻读一次）
    读货舱              1.0s
    看板数据重建        2.0s
"""

import time
from dataclasses import dataclass, field

from . import advice as advice_module
from . import ledger as ledger_module
from . import mapwatch
import logging

from . import shop

logger = logging.getLogger(__name__)
from . import trade

SHOP_EVERY = 0.4
CARGO_EVERY = 1.0
BOARD_EVERY = 2.0

#: 三条并行路线（每条从豐饒的沙漠-N 走到末尾的 -4）。
#: 商人按「第几条线 → 线上第几站」排序，看板一列正好一条线。
LINE_MAPS = [
    ["豐饒的沙漠-1", "仙人掌沙漠-1", "孤獨的沙漠-1", "寂寞的沙漠-1",
     "通往納希貿易區的路", "納希貿易區-1", "納希貿易區-2", "納希貿易區-3",
     "納希貿易區-4"],
    ["豐饒的沙漠-2", "仙人掌沙漠-2", "孤獨的沙漠-2", "寂寞的沙漠-2",
     "通往瑪迦提亞貿易區的路", "瑪迦提亞貿易區-1", "瑪迦提亞貿易區-2",
     "瑪迦提亞貿易區-3", "瑪迦提亞貿易區-4"],
    ["豐饒的沙漠-3", "仙人掌沙漠-3", "孤獨的沙漠-3", "寂寞的沙漠-3",
     "通往古代遺跡的路", "古代遺跡地內部-1", "古代遺跡地內部-2",
     "古代遺跡地內部-3", "古代遺跡地內部-4"],
]

#: 地图名 -> (线路序号, 站序)
MAP_STATION = {name: (line, index)
               for line, maps_in_line in enumerate(LINE_MAPS)
               for index, name in enumerate(maps_in_line)}

#: 兜底：merchant_id 前缀（地图查不到时用）
LINE_ORDER = {"kobi": 0, "dour": 1, "ore": 2}


@dataclass
class State:
    map: str = ""
    advice: list = field(default_factory=list)
    blocks: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)   # 金币 / 负重 / 容量
    goods: list = field(default_factory=list)   # [(名字, 数量 or None)]
    cargo: list = field(default_factory=list)
    board: list = field(default_factory=list)
    note: str = ""
    version: int = 0


def _safe(function, frame, default=None):
    try:
        return function(frame)
    except Exception:
        return default


def merchant_map_of(merchant_id):
    """商人站在哪张图（查 merchant_maps.json：地图名 -> 商人）。"""
    try:
        for map_name, entry in shop.load_merchant_maps().items():
            if entry.get("merchant_id") == merchant_id:
                return map_name
    except Exception:
        pass
    return ""


def _merchant_sort_key(merchant_id):
    """按「第几条线 → 线上第几站」排；查不到就退回 merchant_id 前缀。"""
    map_name = merchant_map_of(merchant_id)
    station = MAP_STATION.get(map_name)
    if station is not None:
        return (station[0], station[1], 0, str(merchant_id or ""))
    prefix, _, suffix = str(merchant_id or "").partition("_")
    try:
        number = int(suffix)
    except (TypeError, ValueError):
        number = 10 ** 9
    return (len(LINE_MAPS), 0, number, str(merchant_id or ""))


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


def _good_name(good_id):
    """商品 id -> 显示名（读不到就用 id 本身）。"""
    try:
        return shop.goods_name(good_id)
    except Exception:
        return good_id


def _as_items(raw):
    """把读到的货统一成 [(good_id, count or None)]；兼容只给 id 的旧调用。"""
    out = []
    for item in raw or []:
        if isinstance(item, (tuple, list)) and len(item) == 2:
            out.append((item[0], item[1]))
        else:
            out.append((item, None))
    return out


def _sell_line(item):
    """卖货建议的一行：去哪（带地图）、有没有已知价、多远。"""
    price = item.get("price")
    hops = item.get("hops")
    map_name = item.get("map") or ""
    where = f"{item['merchant']}（{map_name}）" if map_name else f"{item['merchant']}"
    text = f"{item['good']} → {where}"
    if price:
        text += f" @{price}"
    text += f"，距离 {'?' if hops is None else hops} 张图"
    return text


class TradeSession:
    """一张地图跟踪器 + 记录簿 + 路程估算 -> 可显示的状态。

    视图层只需要 :meth:`update`；``state`` / ``visit`` / ``held`` 等属性是给
    控制台打印「上次读到什么」用的，GUI 只用 ``state``。
    """

    #: 视图可以覆盖（控制台按 ``advice_every`` 放慢读取频率）
    shop_every = SHOP_EVERY
    cargo_every = CARGO_EVERY
    board_every = BOARD_EVERY

    def __init__(self, watcher=None, ledger=None, travel=None):
        self.watcher = watcher or mapwatch.MapWatcher()
        self.ledger = ledger or ledger_module.Ledger()
        self.travel = travel or advice_module.MapTravel()
        self.state = State()
        self._open = False
        #: 节流专用的单调时钟：只在本进程内比较，绝不落盘、不传给 ledger/advice。
        self._mono = time.monotonic
        self._shop_at = 0.0
        self._cargo_at = 0.0
        self._board_at = 0.0
        self._merged = {}
        self._merchant_maps = None
        self._fixed_cache = None
        #: 最近一次成功读到的商店 / 货舱（控制台视图用）
        self.visit = None
        self.held = []
        self.held_items = []          # [(good_id, count or None)]
        self.stats = {"coins": 0, "weight": 0, "capacity": 0}
        self.cargo_known = False
        self._idle_at = 0.0
        self.shop_read = False
        self.cargo_read = False
        self.shop_error = ""
        self.cargo_error = ""
        self.watcher_error = ""

    # ------------------------------------------------------------------
    def current_map(self):
        previous = getattr(self.watcher, "last_map_obs", None)
        return getattr(previous, "map_id", "") or ""

    def _shop_open(self, frame):
        return _safe(trade.find_shop_window, frame, default=False)

    def _cargo_open(self, frame):
        return _safe(trade.find_cargo_window, frame, default=False)

    def update(self, frame, now=None):
        # 落盘 / 有效期 / 建议一律用墙钟：monotonic 只在同一个进程内有意义。
        explicit = now is not None
        now = time.time() if now is None else float(now)
        # 节流用单调时钟。测试会传合成时间轴（< 1e9）精确控制节流，跟随它；
        # 真实调用（None 或墙钟）一律用 self._mono()。
        clock = (now if explicit and not ledger_module.is_wall_clock(now)
                 else self._mono())
        self.shop_read = False
        self.cargo_read = False
        self.shop_error = ""
        self.cargo_error = ""
        self.watcher_error = ""
        try:
            self.watcher.step(frame, now=clock)
        except Exception as exc:
            self.watcher_error = str(exc)
        previous_map = self.state.map
        self.state.map = self.current_map()
        if previous_map and self.state.map and self.state.map != previous_map:
            self._refresh_idle(now)          # 过图后距离全变了，重算一次

        opened = self._shop_open(frame)
        try:
            # 告诉观察器"商店开着没有"：它要扣掉逛店时间，并记"门→商人"样本
            self.watcher.note_shop(clock, opened, map_name=self.state.map)
        except Exception:
            pass
        if opened:
            if not self._open or clock - self._shop_at >= self.shop_every:
                self._read_shop(frame, now)
                self._shop_at = clock
            self._open = True
        else:
            was_open = self._open
            self._open = False
            self._merged = {}
            if was_open:
                self._refresh_idle(now)          # 关商店就重算，别留着旧建议
                self._idle_at = clock
            if self._cargo_open(frame):
                if clock - self._cargo_at >= self.cargo_every:
                    self._read_cargo(frame, now)
                    self._cargo_at = clock
            elif clock - self._idle_at >= self.cargo_every:
                # 商店和货舱都没开：也要给建议，否则开局/过图后整片空白
                self._refresh_idle(now)
                self._idle_at = clock

        if clock - self._board_at >= self.board_every:
            self._read_board(now)
            self._board_at = clock
        # 顶部通栏的数据：金币/负重来自最近一次商店读取，货物来自最近一次货舱读取
        self.state.stats = dict(self.stats)
        self.state.goods = [(_good_name(good_id), count)
                            for good_id, count in self.held_items]
        return self.state

    # ------------------------------------------------------------------
    def _read_shop(self, frame, now):
        try:
            visit = shop.read_visit(frame, self.state.map)
        except Exception as exc:
            self.state.note = f"读商店失败：{exc}"
            self.shop_error = str(exc)
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
        self.visit = visit
        self.shop_read = True
        # 每次都刷新身上的货：卖掉之后库存要立刻反映出来，
        # 不能只在"没有买建议"时才读（否则会一直显示已经卖掉的货）。
        try:
            self.held_items = _as_items(
                shop.read_cargo_items(frame, profile="shop", with_counts=True))
            self.held = [good_id for good_id, count in self.held_items
                         for _ in range(max(1, int(count or 1)))]
        except Exception:
            pass
        self.stats = {"coins": visit.coins if getattr(visit, "coins_known", True) else None,
                      "weight": visit.weight,
                      "capacity": visit.capacity or 135}
        self.cargo_known = bool(getattr(visit, "cargo_known", False))
        self._advise(now, visit, frame=frame)

    def _refresh_idle(self, now):
        """没有商店界面时也走同一套建议逻辑，只是没有当前商店的报价。"""
        if not self.state.map:
            return
        self._advise(now, keep_if_empty=True)

    def _advise(self, now, visit=None, frame=None, keep_if_empty=False):
        """购物建议只有一套：当前商店 → 卖身上的货 → 去买 → 去看看。

        ``visit`` 只是"现在有没有商店报价"这个输入，不是另一套逻辑；
        ``frame`` 只在需要临时读货舱时用（商店开着、买不了的情况）。
        """
        blocks, total = [], 0
        try:
            if visit is not None and getattr(visit, "kind", "") == "random":
                # 随机商人只有一种类型（只卖/只收），离开地图就消失：
                # 只给「买了去固定商人卖」或「就地卖给他」，绝不建议回头找他。
                blocks = advice_module.random_advice(
                    visit, self.ledger, self.travel, held=self.held, now=now)
                total = len(blocks)
            else:
                items = (advice_module.suggest(visit, self.ledger, self.travel, now=now)
                         if visit is not None else [])
                if items:
                    blocks = advice_module.format_suggestions(items)
                    total = len(items)
                if not blocks and frame is not None:
                    # 商店开着但没得买：读右边货舱，看看身上的货该卖给谁
                    try:
                        held_items = shop.read_cargo_items(
                            frame, profile="shop", with_counts=True)
                    except Exception:
                        held_items = []
                    self.held_items = _as_items(held_items)
                    self.held = [good_id for good_id, count in self.held_items
                         for _ in range(max(1, int(count or 1)))]
                if not blocks and self.held_items:
                    held = [good_id for good_id, _c in self.held_items]
                    sell = advice_module.sell_plan(held, self.ledger, self.travel,
                                                   now=now, current_map=self.state.map)
                    if sell:
                        blocks = [[_sell_line(item)]
                                  for item in sell[:advice_module.COLUMNS]]
                        total = len(sell)
                if not blocks:
                    known = self.cargo_known
                    trips = advice_module.buy_trip_plan(
                        self.ledger, self.travel, now=now,
                        current_map=self.state.map,
                        coins=self.stats.get("coins") if known else None,
                        weight=self.stats.get("weight"),
                        capacity=self.stats.get("capacity"))
                    if trips:
                        blocks = advice_module.format_buy_trips(trips)
                        total = len(trips)
                if not blocks:
                    explore = advice_module.explore_plan(
                        self.ledger, self.travel, now=now,
                        current_map=self.state.map)
                    if explore or not keep_if_empty:
                        blocks = advice_module.format_explore(explore)
                        total = len(explore)
        except Exception as exc:
            blocks, total = [[f"建议计算失败：{exc}"]], 1
        if not blocks:
            return
        urgent = any(advice_module.urgency(getattr(s, "left", None)) == "urgent"
                     for s in (locals().get("items") or []))
        if urgent:
            blocks.extend(self._calm_down(now))
            total += 1
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("[建议] map=%s coins=%s weight=%s/%s blocks=%s",
                         self.state.map, self.stats.get("coins"),
                         self.stats.get("weight"), self.stats.get("capacity"),
                         len(blocks))
        self._apply_blocks(blocks, total)


    def _calm_down(self, now, limit=2):
        """有时限的建议旁边给"不想赶"的备选：不紧急的买货机会 + 去看看。"""
        rows = []
        try:
            trips = advice_module.buy_trip_plan(
                self.ledger, self.travel, now=now, current_map=self.state.map,
                coins=self.stats.get("coins") if self.cargo_known else None,
                weight=self.stats.get("weight"),
                capacity=self.stats.get("capacity"))
        except Exception:
            trips = []
        for item in trips:
            if advice_module.urgency(item.get("left")) == "urgent":
                continue
            rows.append(f"　去 {item['merchant']} 買 {item['good']} @{item['price']}"
                        f"，距离 {item.get('hops', 0)} 张图")
            if len(rows) >= limit:
                break
        if len(rows) < limit:
            try:
                explore = advice_module.explore_plan(
                    self.ledger, self.travel, now=now, current_map=self.state.map)
            except Exception:
                explore = []
            for item in explore:
                if len(rows) >= limit:
                    break
                rows.append(f"　去看看 {item['merchant']}（{item['map']}）"
                            f" 距离 {item.get('hops', 0)} 张图")
        if not rows:
            return []
        return [["不想赶？"] + rows]

    def _apply_blocks(self, blocks, total):
        """把「每条一段」的建议块写进 state：扁平文本给控制台，blocks 给 GUI 分列。"""
        blocks = [b for b in blocks if b]
        fold = advice_module.fold_text(total, len(blocks))
        flat = [line for block in blocks for line in block]
        if fold:
            flat.append(fold)
        self.state.blocks = blocks
        self.state.advice = flat or ["（暫無值得跑的建議）"]
        self.state.version += 1

    def _read_cargo(self, frame, now):
        try:
            held_items = shop.read_cargo_items(frame, with_counts=True)
            self.held_items = _as_items(held_items)
            held = [good_id for good_id, _c in self.held_items]
        except Exception as exc:
            self.state.note = f"读货舱失败：{exc}"
            self.cargo_error = str(exc)
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
            lines.append(_sell_line(item))
        self.state.cargo = lines or (["（没有可信收购价，先去附近看看）"] if held else [])
        # 货舱建议也要显示在「当前建议」里（原来只写 cargo，界面看不到）
        blocks = [[line] for line in self.state.cargo] or []
        self._apply_blocks(blocks, len(blocks))
        self.held = list(held)
        self.cargo_read = True
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
