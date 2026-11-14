import tempfile
import unittest
from pathlib import Path

from maplebot import advice, ledger


def visit(map_name, merchant, rows, coins=50, weight=0, refresh=300):
    return {"map": map_name, "merchant_id": "", "merchant": merchant,
            "merchant_kind": "fixed", "refresh_in": refresh,
            "coins": coins, "weight": weight, "capacity": 135,
            "rows": [{"good_id": g, "good": g, "side": side, "price": price}
                     for g, side, price in rows]}


class TravelTest(unittest.TestCase):
    def test_one_hop_default(self):
        travel = advice.MapTravel(edge_times=[], per_hop=60)
        self.assertEqual(travel.hops("貿易地帶岔道", "豐饒的沙漠-1"), 1)
        self.assertAlmostEqual(travel.seconds("貿易地帶岔道", "豐饒的沙漠-1"), 60.0)

    def test_measured_edge_overrides(self):
        graph = {"A": ["B"], "B": ["A"]}
        times = [{"from": "A", "to": "B", "n": 5, "median_fastest": 9.0}]
        travel = advice.MapTravel(graph=graph, edge_times=times, per_hop=60)
        self.assertAlmostEqual(travel.seconds("A", "B"), 9.0)

    def test_few_samples_fall_back(self):
        graph = {"A": ["B"], "B": ["A"]}
        times = [{"from": "A", "to": "B", "n": 1, "median_fastest": 9.0}]
        travel = advice.MapTravel(graph=graph, edge_times=times, per_hop=60)
        self.assertAlmostEqual(travel.seconds("A", "B"), 60.0)


class SuggestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = ledger.Ledger(Path(self.tmp.name) / "obs.jsonl")
        self.graph = {"石铁": ["甲"], "甲": ["石铁"], "乙": ["甲"], "甲2": ["甲"]}
        self.travel = advice.MapTravel(graph=self.graph, edge_times=[], per_hop=60)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_suggestion_when_buyer_expired_before_arrival(self):
        from maplebot import advice as module
        module._merchant_maps = lambda: {"kobi_1": "石铁", "buyer": "甲"}
        module._goods = lambda: {"g": {"name": "货", "buyers": ["buyer"]}}
        self.ledger.record(visit("甲", "收家", [("g", "buy", 99)], refresh=30), now=0)
        current = visit("石铁", "石铁", [("g", "sell", 100)])
        items = module.suggest(_as_visit(current), self.ledger, self.travel, now=0)
        self.assertEqual(items, [])

    def test_suggestion_when_window_holds(self):
        from maplebot import advice as module
        module._merchant_maps = lambda: {"kobi_1": "石铁", "buyer": "甲"}
        module._goods = lambda: {"g": {"name": "货", "buyers": ["buyer"]}}
        self.ledger.record(visit("甲", "收家", [("g", "buy", 99)], refresh=600), now=0)
        current = visit("石铁", "石铁", [("g", "sell", 10)], coins=50)
        items = module.suggest(_as_visit(current), self.ledger, self.travel, now=0)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].profit_per_unit, 89)
        self.assertEqual(items[0].units, 5)      # 50 // 10


class _AsVisit:
    def __init__(self, payload):
        self.map = payload["map"]
        self.merchant = payload["merchant"]
        self.coins = payload["coins"]
        self.weight = payload["weight"]
        self.capacity = payload["capacity"]
        self.rows = [_Row(r) for r in payload["rows"]]


class _Row:
    def __init__(self, row):
        self.good_id = row["good_id"]
        self.good_name = row["good"]
        self.side = row["side"]
        self.price = row["price"]


def _as_visit(payload):
    return _AsVisit(payload)


if __name__ == "__main__":
    unittest.main()
