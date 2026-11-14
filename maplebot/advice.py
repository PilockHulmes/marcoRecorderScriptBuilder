"""单跳商机建议：站在商人 A 的界面里，告诉玩家"买这个，去那里卖"。

规则（TRADE_DESIGN.md 13.7）：

- 只看 A **卖给我** 的行
- 对每件货找它的买家商人（知识库 buyers），再用买家所在地图算路程
- 路程时间：实测优先，没有实测就按 `跳数 × 默认每跳秒数`（默认 60 秒，保守）
- 必须满足：现在有效 + 跑到时买家还没刷新 + 本局剩余时间够
- 排序：**距离优先**，同距离按单件利润降序
"""

import json
from dataclasses import dataclass
from pathlib import Path

from . import ledger as ledger_module

ROOT = Path(__file__).resolve().parents[1]
GOODS_PATH = ROOT / "data" / "trade" / "goods.json"
MERCHANT_MAPS_PATH = ROOT / "data" / "trade" / "merchant_maps.json"
GRAPH_PATH = ROOT / "data" / "trade" / "map_graph.json"
EDGE_TIMES_PATH = ROOT / "data" / "trade" / "edge_times.json"

#: 还没有实测数据时，每一跳按这个秒数估（刻意保守：玩家不熟练）
DEFAULT_SECONDS_PER_HOP = 60.0
TIER1_MAX = 13      # 一类货：买价 ≤ 13 值得买
TIER2_MAX = 40      # 二类货：买价 ≤ 40 值得买
#: 一条边至少要这么多样本才敢用实测值
MIN_SAMPLES = 3


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


class MapTravel:
    """地图之间的距离（秒）。实测优先，否则按跳数估。"""

    def __init__(self, graph=None, edge_times=None, per_hop=DEFAULT_SECONDS_PER_HOP):
        self.graph = graph if graph is not None else _read_json(GRAPH_PATH, {})
        self.per_hop = float(per_hop)
        self.times = {}
        for row in (edge_times if edge_times is not None else _read_json(EDGE_TIMES_PATH, [])):
            if row.get("n", 0) >= MIN_SAMPLES:
                self.times[frozenset((row["from"], row["to"]))] = float(row["median_fastest"])

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

    def seconds(self, a, b):
        """逐段相加：有实测用实测，没有就用每跳估计。"""
        route = self.path(a, b)
        if route is None:
            return None
        total = 0.0
        for x, y in zip(route, route[1:]):
            total += self.times.get(frozenset((x, y)), self.per_hop)
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


def _merchant_maps():
    data = _read_json(MERCHANT_MAPS_PATH, {})
    return {item["merchant_id"]: item.get("map", "") for item in data.values()
            if item.get("merchant_id")}


def _goods():
    data = _read_json(GOODS_PATH, {})
    return {g["id"]: g for g in data.get("goods", [])}


def suggest(visit, ledger=None, travel=None, now=0.0, remaining=None, limit=5):
    """visit = shop.Visit（当前打开的商店）；返回按距离排序的建议列表。"""
    ledger = ledger if ledger is not None else ledger_module.Ledger()
    travel = travel if travel is not None else MapTravel()
    goods = _goods()
    where = _merchant_maps()
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
                    sell_at=observation.get("merchant", buyer_map), sell_price=best,
                    hops=hops, seconds=round(seconds, 1),
                    profit_per_unit=profit, profit_total=profit * units,
                    reason="文档阈值" if cheap else "记忆比价",
                ))
            elif cheap:
                # 第一类：价格已经够低，不需要先知道买家报价，直接建议去找该货的买家
                out.append(Suggestion(
                    good_id=row.good_id, good=row.good_name, buy_at=visit.merchant or visit.map,
                    buy_price=row.price, units=units,
                    sell_at=buyer_map, sell_price=None,
                    hops=hops, seconds=round(seconds, 1),
                    profit_per_unit=0, profit_total=0,
                    reason="价格够低（去买家处再看价）", price_known=False,
                ))

    out.sort(key=lambda s: (s.hops, -s.profit_total))
    return out[:limit]


def format_suggestions(items):
    if not items:
        return ["（暂无值得跑的建议）"]
    lines = []
    for s in items:
        if s.price_known:
            lines.append(f"  {s.good}：在 {s.buy_at} 买 @{s.buy_price} × {s.units} 个"
                         f" → {s.sell_at} 卖 @{s.sell_price}"
                         f"（{s.hops} 张图 / 约 {int(s.seconds)} 秒，赚 {s.profit_total}）")
        else:
            lines.append(f"  {s.good}：便宜（@{s.buy_price}），可买 {s.units} 个"
                         f" → 去 {s.sell_at} 找买家（{s.hops} 张图 / 约 {int(s.seconds)} 秒）")
    return lines
