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
from . import shop
from . import trade

SHOP_EVERY = 0.4
CARGO_EVERY = 1.0
BOARD_EVERY = 2.0

#: 固定商人的线路顺序：kobi < dour < ore，再按 merchant_id 的数字序号
LINE_ORDER = {"kobi": 0, "dour": 1, "ore": 2}


@dataclass
class State:
    map: str = ""
    advice: list = field(default_factory=list)
    cargo: list = field(default_factory=list)
    board: list = field(default_factory=list)
    note: str = ""
    version: int = 0


def _safe(function, frame, default=None):
    try:
        return function(frame)
    except Exception:
        return default


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
        self._shop_at = 0.0
        self._cargo_at = 0.0
        self._board_at = 0.0
        self._merged = {}
        self._merchant_maps = None
        self._fixed_cache = None
        #: 最近一次成功读到的商店 / 货舱（控制台视图用）
        self.visit = None
        self.held = []
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
        now = time.monotonic() if now is None else float(now)
        self.shop_read = False
        self.cargo_read = False
        self.shop_error = ""
        self.cargo_error = ""
        self.watcher_error = ""
        try:
            self.watcher.step(frame, now=now)
        except Exception as exc:
            self.watcher_error = str(exc)
        self.state.map = self.current_map()

        opened = self._shop_open(frame)
        if opened:
            if not self._open or now - self._shop_at >= self.shop_every:
                self._read_shop(frame, now)
                self._shop_at = now
            self._open = True
        else:
            self._open = False
            self._merged = {}
            if self._cargo_open(frame):
                if now - self._cargo_at >= self.cargo_every:
                    self._read_cargo(frame, now)
                    self._cargo_at = now

        if now - self._board_at >= self.board_every:
            self._read_board(now)
            self._board_at = now
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
        lines = []
        try:
            # 三级建议：当前商店有生意 -> 去别处买便宜货 -> 去未知/过期的商人看看
            items = advice_module.suggest(visit, self.ledger, self.travel, now=now)
            if items:
                lines = advice_module.format_suggestions(items)
            else:
                trips = advice_module.buy_trip_plan(self.ledger, self.travel,
                                                    now=now, current_map=self.state.map)
                if trips:
                    lines = advice_module.format_buy_trips(trips)
                else:
                    explore = advice_module.explore_plan(
                        self.ledger, self.travel, now=now,
                        current_map=self.state.map)
                    for item in explore:
                        lines.append(f"去看看 {item['merchant']}({item['map']}) "
                                     f"{item['hops']} 张图")
                    if not lines:
                        lines = advice_module.format_suggestions([])
        except Exception as exc:
            lines = [f"建议计算失败：{exc}"]
        self.state.advice = lines
        self.state.version += 1

    def _read_cargo(self, frame, now):
        try:
            held = shop.read_cargo_items(frame)
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
            lines.append(f"{item['good']} → {item['merchant']}({item['map']}) "
                         f"@{item['price']}（{hops} 张图）")
        self.state.cargo = lines or (["（没有可信收购价，先去附近看看）"] if held else [])
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
