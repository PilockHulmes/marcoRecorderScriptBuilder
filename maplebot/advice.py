"""单跳商机建议：站在商人 A 的界面里，告诉玩家"买这个，去那里卖"。

三条建议通道：

- :func:`suggest`：**当前打开商店**里买 → 谁收；
- :func:`buy_trip_plan`：别处有便宜货、现在跑过去还来得及 → 专程去买；
- :func:`explore_plan`：没有生意时，去找价格未知或已过期的商人看看。

另有 :func:`random_advice`：随机商人（没有固定商人的地图）只卖 / 只收的
一次性建议。随机商人的记录没有 ``merchant_id``，任何计划都不会把它当成
目的地（见 :func:`_fixed_observation`）。

规则（TRADE_DESIGN.md 13.7）：

- 只看 A **卖给我** 的行
- 对每件货找它的买家商人（知识库 buyers），再用买家所在地图算路程
- 路程时间：实测优先，没有实测就按 `跳数 × 默认每跳秒数`（默认 60 秒，保守）
- 必须满足：现在有效 + 跑到时买家还没刷新 + 本局剩余时间够
- 排序：**距离优先**，同距离按单件利润降序
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import ledger as ledger_module

ROOT = Path(__file__).resolve().parents[1]
GOODS_PATH = ROOT / "data" / "trade" / "goods.json"
MERCHANT_MAPS_PATH = ROOT / "data" / "trade" / "merchant_maps.json"
GRAPH_PATH = ROOT / "data" / "trade" / "map_graph.json"
EDGE_TIMES_PATH = ROOT / "data" / "trade" / "edge_times.json"
EDGE_RAW_PATH = ROOT / "data" / "trade" / "edge_times_raw.jsonl"

#: 还没有实测数据时，每一跳按这个秒数估（刻意保守：玩家不熟练）
DEFAULT_SECONDS_PER_HOP = 60.0
TIER1_MAX = 13      # 一类货：买价 ≤ 13 值得买
TIER2_MAX = 40      # 二类货：买价 ≤ 40 值得买
VOLATILE_MAX = 300  # 波动货：价格区间本来就大，只挡明显离谱的报价
#: 一条边至少要这么多样本才敢用实测值
MIN_SAMPLES = 3


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _wall_now(now):
    """建议里的 ``now`` 一律是墙钟；缺省用 ``time.time()``。"""
    return time.time() if now is None else float(now)


class MapTravel:
    """地图之间的距离（秒）。实测优先，否则按跳数估。

    时间表是**有向**的：``(from, to)`` 和 ``(to, from)`` 是两条独立的边。
    反向没有实测时照常用默认每跳秒数，不会把正向的实测倒过来用。
    """

    def __init__(self, graph=None, edge_times=None, per_hop=DEFAULT_SECONDS_PER_HOP):
        self.graph = graph if graph is not None else _read_json(GRAPH_PATH, {})
        self.per_hop = float(per_hop)
        self.times = {}
        self.portal_times = {}      # {(from, from_portal, to, to_portal): 秒}
        self.reload(edge_times)

    def reload(self, edge_times=None):
        """重新算耗时：优先用运行时原始样本（最快 3 次的均值），否则用汇总文件。"""
        from collections import defaultdict

        self.times = {}
        self.portal_times = {}
        if edge_times is not None:        # 显式传入就用它（测试/离线用）
            for row in edge_times:
                if row.get("n", 0) >= MIN_SAMPLES:
                    self.times[(row["from"], row["to"])] = float(row["median_fastest"])
            return
        raw = []
        try:
            if EDGE_RAW_PATH.exists():
                raw = [json.loads(line) for line in
                       EDGE_RAW_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
        except Exception:
            raw = []
        if raw:
            buckets = defaultdict(list)
            portal_buckets = defaultdict(list)
            for item in raw:
                try:
                    seconds = float(item["seconds"])
                except Exception:
                    continue
                buckets[(item["from"], item["to"])].append(seconds)
                from_portal = item.get("from_portal")
                to_portal = item.get("to_portal")
                if from_portal and to_portal:
                    key = (item["from"], tuple(from_portal),
                           item["to"], tuple(to_portal))
                    portal_buckets[key].append(seconds)
            for pair, values in buckets.items():
                if len(values) >= MIN_SAMPLES:
                    fastest = sorted(values)[:3]
                    self.times[pair] = sum(fastest) / len(fastest)
            for key, values in portal_buckets.items():
                if len(values) >= MIN_SAMPLES:
                    fastest = sorted(values)[:3]
                    self.portal_times[key] = sum(fastest) / len(fastest)
            return
        for row in (edge_times if edge_times is not None else _read_json(EDGE_TIMES_PATH, [])):
            if row.get("n", 0) >= MIN_SAMPLES:
                self.times[(row["from"], row["to"])] = float(row["median_fastest"])

    def path(self, a, b):
        """BFS 最短跳数路径（节点列表）；不可达返回 None。"""
        if a == b:
            return [a]
        previous = {a: None}
        queue = [a]
        while queue:
            node = queue.pop(0)
            for nxt in self.graph.get(node, []):
                if nxt in previous:
                    continue
                previous[nxt] = node
                if nxt == b:
                    walk = [b]
                    while walk[-1] != a:
                        walk.append(previous[walk[-1]])
                    return list(reversed(walk))
                queue.append(nxt)
        return None

    def hops(self, a, b):
        route = self.path(a, b)
        return None if route is None else len(route) - 1

    def edge_seconds(self, a, b, from_portal=None, to_portal=None):
        """单条边的耗时：门级实测 → 地图级实测 → 默认每跳。"""
        if from_portal is not None and to_portal is not None:
            key = (a, tuple(from_portal), b, tuple(to_portal))
            if key in self.portal_times:
                return self.portal_times[key]
        return self.times.get((a, b))

    def seconds(self, a, b):
        """逐段相加：这一方向有实测用实测，没有就用每跳估计。"""
        route = self.path(a, b)
        if route is None:
            return None
        total = 0.0
        for x, y in zip(route, route[1:]):
            total += self.times.get((x, y), self.per_hop)
        return total


@dataclass
class Suggestion:
    good_id: str
    good: str
    buy_at: str
    buy_price: int
    units: int
    sell_at: str
    sell_price: int | None
    hops: int
    seconds: float
    profit_per_unit: int
    profit_total: int
    reason: str
    price_known: bool = True
    route: list = field(default_factory=list)
    left: float | None = None      # 到达时买家价格还剩多少秒（越少越赶）
    #: 买点所在地图（显示「在 石鉄（豐饒的沙漠-1）」用；老测试直接构造时可为空）
    buy_map: str = ""
    #: 卖点所在地图（``sell_at`` 是商人名时用来补全；为空则不显示）
    sell_map: str = ""


def _merchant_maps():
    data = _read_json(MERCHANT_MAPS_PATH, {})
    return {item["merchant_id"]: item.get("map", "") for item in data.values()
            if item.get("merchant_id")}


def _merchant_names():
    """merchant_id -> 游戏内繁体名（没有 game_name 才退回文档名）。"""
    data = _read_json(MERCHANT_MAPS_PATH, {})
    names = {}
    for item in data.values():
        merchant_id = item.get("merchant_id")
        if merchant_id:
            names[merchant_id] = (item.get("game_name") or item.get("merchant")
                                  or merchant_id)
    return names


def _goods():
    data = _read_json(GOODS_PATH, {})
    return {g["id"]: g for g in data.get("goods", [])}


def _price_limit(good):
    """这类货的“便宜”上限：一类 13、二类 40、波动货 300。"""
    tier = (good or {}).get("tier")
    if tier == "tier1":
        return TIER1_MAX
    if tier == "tier2":
        return TIER2_MAX
    return VOLATILE_MAX


def _fixed_observation(observation):
    """只有固定商人的观察才有 ``merchant_id``。

    随机商人没有 ``merchant_id``（见 :func:`maplebot.shop.identify`），玩家
    一离开地图他就消失，所以这种记录只能说明“这里有什么货”，**绝不能当成
    建议的目的地**（不能“买了再回来卖给他”）。
    """
    return isinstance(observation, dict) and bool(observation.get("merchant_id"))


def suggest(visit, ledger=None, travel=None, now=None, remaining=None, limit=5):
    """visit = shop.Visit（当前打开的商店）；返回按距离排序的建议列表。"""
    now = _wall_now(now)
    ledger = ledger if ledger is not None else ledger_module.Ledger()
    travel = travel if travel is not None else MapTravel()
    goods = _goods()
    where = _merchant_maps()
    names = _merchant_names()
    observations = ledger.load()

    out = []
    for row in getattr(visit, "rows", []):
        if row.side != "sell":
            continue
        good = goods.get(row.good_id, {})
        for buyer_id in good.get("buyers", []):
            buyer_map = where.get(buyer_id, "")
            if not buyer_map or buyer_map == visit.map:
                continue
            seconds = travel.seconds(visit.map, buyer_map)
            if seconds is None:
                continue
            if remaining is not None and seconds > remaining:
                continue
            arrival = now + seconds
            best = None
            best_until = None
            for observation in observations:
                if observation.get("map") != buyer_map:
                    continue
                if ledger.valid_until(observation) <= arrival:
                    continue
                for other in observation.get("rows", []):
                    if other.get("good_id") != row.good_id or other.get("side") != "buy":
                        continue
                    price = int(other.get("price", 0))
                    if price > 0 and (best is None or price > best):
                        best = price
                        best_until = ledger.valid_until(observation)
            left = (best_until - arrival) if best_until else None
            units = ledger_module.max_units(row.price, visit.coins, visit.weight,
                                            visit.capacity or 135)
            if units <= 0:
                continue
            hops = travel.hops(visit.map, buyer_map) or 0
            threshold = TIER1_MAX if good.get("tier") == "tier1" else TIER2_MAX
            cheap = row.price <= threshold

            if best:
                profit = best - row.price
                if profit <= 0:
                    continue
                out.append(Suggestion(
                    good_id=row.good_id, good=row.good_name, buy_at=visit.merchant or visit.map,
                    buy_price=row.price, units=units,
                    sell_at=names.get(buyer_id) or buyer_map, sell_price=best,
                    hops=hops, seconds=round(seconds, 1),
                    profit_per_unit=profit, profit_total=profit * units,
                    reason="文档阈值" if cheap else "记忆比价",
                    route=travel.path(visit.map, buyer_map) or [],
                    buy_map=visit.map, sell_map=buyer_map, left=left,
                ))
            elif cheap:
                # 第一类：价格已经够低，不需要先知道买家报价，直接建议去找该货的买家
                out.append(Suggestion(
                    good_id=row.good_id, good=row.good_name, buy_at=visit.merchant or visit.map,
                    buy_price=row.price, units=units,
                    sell_at=names.get(buyer_id) or buyer_map, sell_price=None,
                    hops=hops, seconds=round(seconds, 1),
                    profit_per_unit=0, profit_total=0,
                    reason="够便宜，卖给他稳赚", price_known=False,
                    route=travel.path(visit.map, buyer_map) or [],
                    buy_map=visit.map, sell_map=buyer_map, left=None,
                ))

    out.sort(key=lambda s: (s.hops, -s.profit_total))
    return out[:limit]


def sell_plan(held_goods, ledger=None, travel=None, now=None, current_map="", limit=5):
    """身上带着的货该去哪卖：按已知收购价和距离给建议。"""
    now = _wall_now(now)
    ledger = ledger if ledger is not None else ledger_module.Ledger()
    travel = travel if travel is not None else MapTravel()
    where = _merchant_maps()
    goods = _goods()
    names = _merchant_names()
    out = []
    for good_id in held_goods:
        good = goods.get(good_id, {})
        for buyer_id in good.get("buyers", []):
            buyer_map = where.get(buyer_id, "")
            if not buyer_map:
                continue
            # 当前地图的买家**不跳过**：就地卖永远比跑图好，距离记 0
            seconds = travel.seconds(current_map, buyer_map) if current_map else None
            arrival = now + (seconds or 0)
            best = None
            for observation in ledger.load():
                if not _fixed_observation(observation):
                    continue
                if observation.get("map") != buyer_map:
                    continue
                if ledger.valid_until(observation) <= arrival:
                    continue
                for row in observation.get("rows", []):
                    if row.get("good_id") != good_id or row.get("side") != "buy":
                        continue
                    price = int(row.get("price", 0))
                    if price > 0 and (best is None or price > best):
                        best = price
            # 没有已知收购价也照样给方向：谁收是确定的，价格到了才知道。
            out.append({"good": good.get("name", good_id), "map": buyer_map,
                        "merchant": names.get(buyer_id, buyer_id),
                        "merchant_id": buyer_id,
                        "price": best,
                        "seconds": seconds,
                        "hops": 0 if buyer_map == current_map else (
                            travel.hops(current_map, buyer_map) if current_map else None)})
    out.sort(key=lambda r: (r["hops"] if r["hops"] is not None else 99,
                            -(r["price"] or 0)))
    return out[:limit]


def buy_trip_plan(ledger=None, travel=None, now=None, current_map="",
                  remaining=None, limit=5, coins=None, weight=None, capacity=None):
    """别处有便宜货、现在跑过去还来得及：建议专程去买。

    数据来源是记录簿里所有**还没过期**的 ``side == "sell"`` 行（他卖给我）。
    过滤条件：

    - 报价不在当前地图（人已经在这儿了，直接买就行，不用“跑一趟”）；
    - 价格不超过该商品档位阈值（一类 13 / 二类 40 / 波动货 300）；
    - 现在还没过期，并且 ``now + 路程`` 到达时也还没过期；
    - 有本局剩余时间 ``remaining`` 时，路程不能超过它。

    排序：**距离优先**，同距离按价格从低到高。``left`` 是到达时仍剩余的秒数。
    """
    now = _wall_now(now)
    ledger = ledger if ledger is not None else ledger_module.Ledger()
    travel = travel if travel is not None else MapTravel()
    goods = _goods()
    names = _merchant_names()

    best = {}
    for observation in ledger.load():
        if not _fixed_observation(observation):
            continue                       # 随机商人记录不能当目的地
        map_name = observation.get("map", "")
        if not map_name or map_name == current_map:
            continue
        valid_until = ledger.valid_until(observation)
        if valid_until <= now:
            continue
        seconds = travel.seconds(current_map, map_name)
        if seconds is None:
            continue
        if remaining is not None and seconds > remaining:
            continue
        arrival = now + seconds
        left = valid_until - arrival
        if left < 0.1:
            continue                       # 跑到了也已经刷新（或只剩 0.1 秒），白跑
        hops = travel.hops(current_map, map_name) or 0
        merchant_id = observation.get("merchant_id", "")
        merchant = (names.get(merchant_id) or observation.get("merchant")
                    or merchant_id or map_name)
        for row in observation.get("rows", []):
            if row.get("side") != "sell":
                continue
            good_id = row.get("good_id", "")
            price = int(row.get("price", 0))
            if price <= 0 or not good_id:
                continue
            good = goods.get(good_id, {})
            if price > _price_limit(good):
                continue
            if coins is not None and ledger_module.max_units(
                    price, coins, weight or 0, capacity or 135) <= 0:
                continue                   # 买不起或装不下：别让人白跑
            item = {
                "good": good.get("name") or row.get("good") or good_id,
                "good_id": good_id,
                "price": price,
                "merchant": merchant,
                "merchant_id": merchant_id,
                "map": map_name,
                "hops": hops,
                "seconds": round(seconds, 1),
                "left": round(left, 1),
            }
            # 同一商人同一件货可能有多条仍然有效的观察：留最便宜的；
            # 同价留到得最晚的（窗口更宽）。
            key = (merchant_id or map_name, good_id)
            previous = best.get(key)
            if (previous is None or price < previous["price"]
                    or (price == previous["price"]
                        and item["left"] > previous["left"])):
                best[key] = item

    out = list(best.values())
    out.sort(key=lambda r: (r["hops"], r["price"], -r["left"], r["seconds"]))
    return out[:limit]


def explore_plan(ledger=None, travel=None, now=None, current_map="",
                 remaining=None, limit=3):
    """没有生意时：就近找价格未知/已过期的商人去看看。"""
    now = _wall_now(now)
    ledger = ledger if ledger is not None else ledger_module.Ledger()
    travel = travel if travel is not None else MapTravel()
    where = _merchant_maps()
    names = _merchant_names()
    last_seen = {}
    for observation in ledger.load():
        if not _fixed_observation(observation):
            continue                       # 随机商人记录不能当目的地
        merchant_id = observation.get("merchant_id")
        last_seen[merchant_id] = max(last_seen.get(merchant_id, 0),
                                     ledger.valid_until(observation))
    out = []
    for merchant_id, map_name in where.items():
        if not map_name or map_name == current_map:
            continue
        if last_seen.get(merchant_id, 0) > now:
            continue                       # 还有效，不用去看
        seconds = travel.seconds(current_map, map_name) if current_map else None
        if seconds is None:
            continue
        if remaining is not None and seconds > remaining:
            continue
        out.append({"merchant_id": merchant_id,
                    "merchant": names.get(merchant_id, merchant_id),
                    "map": map_name,
                    "hops": travel.hops(current_map, map_name),
                    "seconds": seconds,
                    "fresh": last_seen.get(merchant_id, 0) > 0})
    out.sort(key=lambda r: (r["hops"] if r["hops"] is not None else 99, r["seconds"]))
    return out[:limit]


def _place(merchant, map_name=""):
    """「石鉄（豐饒的沙漠-1）」；名字和地图相同或地图缺失时不重复。"""
    name = str(merchant or map_name or "?")
    map_name = str(map_name or "")
    if map_name and map_name != name:
        return f"{name}（{map_name}）"
    return name


def _folded(items):
    """只展开 top-1，其余折叠成一行（建议区只有 4 行高）。"""
    extra = max(0, len(items) - 1)
    return [f"还有 {extra} 条…"] if extra else []


COLUMNS = 8          # 建议列高度够，竖排显示多条


def fold_text(total, shown):
    """还有几条没展开；没有就返回空串。"""
    rest = total - shown
    return f"還有 {rest} 條…" if rest > 0 else ""


def format_suggestions(items):
    """当前商店的建议：**按商品分组**，一组一列。

    每组第一行是商店，之后每条是「買 … 個到 … 賣，距离 N 张图」——
    同一件货有几个卖点就列几行，信息密度比一条建议占三行高。
    """
    if not items:
        return [["（暫無值得跑的建議）"]]

    groups = {}
    for s in items:
        groups.setdefault((s.buy_at, s.good, s.buy_price, s.units), []).append(s)

    blocks = []
    for _key, group in list(groups.items())[:COLUMNS]:
        first = group[0]
        block = [f"在 {_place(first.buy_at, first.buy_map)}",
                 f"  買 {first.good} @{first.buy_price} × {first.units} 個"]
        for s in group[:3]:
            sell_at = s.sell_at or "?"
            # 第一行：去哪卖（带地图，玩家对地图比商人名敏感）
            head = f"  → {_place(sell_at, s.sell_map)} 賣"
            if s.price_known and s.sell_price is not None:
                head += f" @{s.sell_price}"
            # 第二行：距离与收益
            tail = f"     距离 {s.hops} 张图"
            if s.price_known and s.sell_price is not None:
                tail += f"，賺 {s.profit_total}"
            block.append(head)
            block.append(tail + leave_mark(getattr(s, "left", None)))
        blocks.append(block)
    return blocks


URGENT_SEC = 45      # 到达后剩余少于这个就算"赶"
TIGHT_SEC = 120      # 少于这个算"有点紧"


def urgency(left):
    """到达时剩余秒数 -> 'urgent' / 'tight' / ''。"""
    if left is None:
        return ""
    if left <= URGENT_SEC:
        return "urgent"
    if left <= TIGHT_SEC:
        return "tight"
    return ""


def leave_mark(left):
    """显示用的剩余时间标记：赶的话带 ⚠。"""
    level = urgency(left)
    if not level:
        return ""
    total = max(0, int(left))
    text = f"{total // 60}:{total % 60:02d}"
    return f"　⚠ 剩 {text}" if level == "urgent" else f"　剩 {text}"


def _clock(seconds):
    """秒数 -> MM:SS（建议里显示「到了还剩」）。"""
    total = max(0, int(seconds))
    return f"{total // 60}:{total % 60:02d}"


def format_buy_trips(items):
    """专程去买：按出发商人分组，一组一列，组内每个商品一行。"""
    if not items:
        return format_suggestions([])
    groups = {}
    for item in items:
        groups.setdefault((item.get("merchant"), item.get("map", "")), []).append(item)
    blocks = []
    for (merchant, map_name), group in list(groups.items())[:COLUMNS]:
        block = [f"去 {_place(merchant, map_name)}"]
        for item in group[:3]:
            left = item.get("left")
            level = urgency(left)
            if level == "urgent":
                tail = f"　⚠ 剩 {_clock(left)}"
            elif left is not None:
                tail = f"　到了还剩 {_clock(left)}"
            else:
                tail = ""
            block.append(f"  買 {item['good']} @{item['price']} "
                         f"距离 {item.get('hops', 0)} 张图{tail}")
        blocks.append(block)
    return blocks


def format_explore(items):
    """去看看：一行一个商人（不带地图），按距离从近到远。"""
    if not items:
        return format_suggestions([])
    blocks = []
    for item in items[:COLUMNS]:
        hops = item.get("hops")
        blocks.append([f"去看看 {_place(item.get('merchant'), item.get('map', ''))} "
                       f"距离 {'?' if hops is None else hops} 张图"])
    return blocks


def _observed_buy_price(observations, ledger, merchant_id, map_name, good_id, at):
    """固定买家在 ``at`` 时刻仍然有效的收购价；没记录就返回 None。

    这里只用来**显示**「賣 @22」，不是推荐的前提：没有报价也照样建议去
    他的地图（价格到那儿再看）。随机商人的记录不能提供任何目的地的价格。
    """
    best = None
    for observation in observations or []:
        if not isinstance(observation, dict) or observation.get("map") != map_name:
            continue
        known_id = observation.get("merchant_id") or ""
        if known_id and known_id != merchant_id:
            continue
        try:
            valid_until = ledger.valid_until(observation)
        except Exception:
            valid_until = 0.0
        if valid_until <= at:
            continue
        for other in observation.get("rows", []) or []:
            if not isinstance(other, dict):
                continue
            if other.get("good_id") != good_id or other.get("side") != "buy":
                continue
            try:
                price = int(other.get("price", 0))
            except (TypeError, ValueError):
                continue
            if price > 0 and (best is None or price > best):
                best = price
    return best


def random_sell_plan(visit, ledger=None, travel=None, now=None, limit=2):
    """随机商人只卖货：挑二类（≤40）且买得起的，按到固定买家的距离排序。

    返回 1~2 条候选（``limit``）；随机商人所在地图只作为**起点**，``map``
    永远是 ``merchant_maps.json`` 里的固定商人地图。
    """
    now = _wall_now(now)
    ledger = ledger if ledger is not None else ledger_module.Ledger()
    travel = travel if travel is not None else MapTravel()
    goods = _goods()
    where = _merchant_maps()
    names = _merchant_names()
    observations = ledger.load()
    current = getattr(visit, "map", "") or ""
    coins = int(getattr(visit, "coins", 0) or 0)
    weight = int(getattr(visit, "weight", 0) or 0)
    capacity = int(getattr(visit, "capacity", 0) or 0) or 135

    candidates = []
    for row in getattr(visit, "rows", None) or []:
        if getattr(row, "side", "") != "sell":
            continue
        good_id = getattr(row, "good_id", "") or ""
        good = goods.get(good_id, {})
        if good.get("tier") != "tier2":
            continue                       # 随机商人只碰二类货
        price = int(getattr(row, "price", 0) or 0)
        if price <= 0 or price > TIER2_MAX:
            continue
        units = ledger_module.max_units(price, coins, weight, capacity)
        if units <= 0:
            continue                       # 连 1 件都买不起/装不下，不推荐
        for buyer_id in good.get("buyers", []) or []:
            buyer_map = where.get(buyer_id, "")
            if not buyer_map or buyer_map == current:
                continue                   # 只考虑固定商人；不留在他自己地图
            seconds = travel.seconds(current, buyer_map)
            if seconds is None:
                continue
            candidates.append({
                "good_id": good_id,
                "good": good.get("name") or getattr(row, "good_name", "") or good_id,
                "price": price,
                "units": units,
                "merchant_id": buyer_id,
                "merchant": names.get(buyer_id) or buyer_id,
                "map": buyer_map,
                "from_map": current,
                "hops": travel.hops(current, buyer_map) or 0,
                "seconds": round(seconds, 1),
                "sell_price": _observed_buy_price(
                    observations, ledger, buyer_id, buyer_map, good_id, now + seconds),
            })
    candidates.sort(key=lambda item: (item["seconds"], item["hops"],
                                      item["good_id"], item["merchant_id"]))
    return candidates[:limit]


def random_buy_plan(visit, held=()):
    """随机商人只收货：拿身上带着的货去匹配他收的商品。"""
    goods = _goods()
    counts = {}
    for good_id in held or []:
        if good_id:
            counts[good_id] = counts.get(good_id, 0) + 1
    out = []
    seen = set()
    for row in getattr(visit, "rows", None) or []:
        if getattr(row, "side", "") != "buy":
            continue
        good_id = getattr(row, "good_id", "") or ""
        price = int(getattr(row, "price", 0) or 0)
        if not good_id or price <= 0 or good_id in seen:
            continue
        units = counts.get(good_id, 0)
        if units <= 0:
            continue
        seen.add(good_id)
        out.append({
            "good_id": good_id,
            "good": goods.get(good_id, {}).get("name")
                    or getattr(row, "good_name", "") or good_id,
            "price": price,
            "units": units,
            "map": getattr(visit, "map", "") or "",
        })
    out.sort(key=lambda item: (-item["price"], item["good_id"]))
    return out


def format_random_sell(items):
    """随机商人（卖货型）：每条 3 行。"""
    if not items:
        return format_suggestions([])
    blocks = []
    for item in items[:COLUMNS]:
        tail = (f"賣 @{item['sell_price']}" if item.get("sell_price") else "賣")
        from_map = item.get("from_map") or ""
        where = f"在 隨機商人（{from_map}）" if from_map else "在 隨機商人"
        blocks.append([
            where,
            f"  買 {item['good']} @{item['price']} × {item['units']} 個",
            f"  → {_place(item.get('merchant'), item.get('map', ''))} {tail}",
            f"     距离 {item.get('hops', 0)} 张图",
        ])
    return blocks


def format_random_buy(items):
    """随机商人（收货型）：每条 2 行，不写「就地成交」。"""
    if not items:
        return [["随机商人只收货，你身上没有他要的"]]
    blocks = []
    for item in items[:COLUMNS]:
        from_map = item.get("map") or ""
        where = f"在 隨機商人（{from_map}）" if from_map else "在 隨機商人"
        blocks.append([
            where,
            f"  賣 {item['good']} @{item['price']} × {item['units']} 個",
        ])
    return blocks


def random_advice(visit, ledger=None, travel=None, held=(), now=None, limit=2):
    """``visit.kind == "random"`` 时给视图的建议行。

    随机商人只有一种类型（要么只卖、要么只收），所以这里只走一个分支：
    卖货型 -> 买了去固定商人卖；收货型 -> 有货就地卖、没货就明说。
    任何情况下都**不**建议玩家再回来找这个商人。
    """
    now = _wall_now(now)
    rows = list(getattr(visit, "rows", None) or [])
    if any(getattr(row, "side", "") == "sell" for row in rows):
        return format_random_sell(
            random_sell_plan(visit, ledger, travel, now=now, limit=limit))
    if any(getattr(row, "side", "") == "buy" for row in rows):
        return format_random_buy(random_buy_plan(visit, held))
    return format_suggestions([])
