import tempfile
import unittest
from pathlib import Path

from maplebot import ledger


def visit(map_name, merchant, rows, refresh=60):
    return {"map": map_name, "merchant_id": "x", "merchant": merchant,
            "merchant_kind": "fixed", "refresh_in": refresh,
            "coins": 50, "weight": 0, "capacity": 135,
            "rows": [{"good_id": g, "good": g, "side": side, "price": price}
                     for g, side, price in rows]}


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = ledger.Ledger(Path(self.tmp.name) / "obs.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_record_and_reload(self):
        self.ledger.record(visit("A", "甲", [("honey", "buy", 50)]), now=1000)
        self.assertEqual(len(self.ledger.load()), 1)

    def test_best_bid_picks_highest(self):
        self.ledger.record(visit("A", "甲", [("honey", "buy", 50)]), now=1000)
        self.ledger.record(visit("B", "乙", [("honey", "buy", 80)]), now=1010)
        best = self.ledger.best_bid("honey", at=1020)
        self.assertEqual(best["price"], 80)
        self.assertEqual(best["map"], "B")

    def test_expired_observation_ignored(self):
        self.ledger.record(visit("A", "甲", [("honey", "buy", 50)], refresh=30), now=1000)
        self.assertIsNotNone(self.ledger.best_bid("honey", at=1020))
        self.assertIsNone(self.ledger.best_bid("honey", at=1040))

    def test_arrival_time_check(self):
        """现在有效、但 25 秒后（走到了）已过期 -> 不能推荐。"""
        self.ledger.record(visit("A", "甲", [("honey", "buy", 50)], refresh=30), now=1000)
        self.assertIsNone(self.ledger.best_bid("honey", at=1035))

    def test_offers_only_sell_side(self):
        self.ledger.record(visit("A", "甲", [("honey", "buy", 50), ("silk", "sell", 20)]), now=1000)
        offers = self.ledger.offers(at=1010)
        self.assertEqual([o["good_id"] for o in offers], ["silk"])

    def test_exclude_current_map(self):
        self.ledger.record(visit("A", "甲", [("honey", "buy", 50)]), now=1000)
        self.assertIsNone(self.ledger.best_bid("honey", at=1010, exclude_map="A"))


class MaxUnitsTest(unittest.TestCase):
    def test_limited_by_coins(self):
        self.assertEqual(ledger.max_units(price=13, coins=50, weight=0, capacity=135), 3)

    def test_limited_by_room(self):
        self.assertEqual(ledger.max_units(price=1, coins=1000, weight=130, capacity=135), 5)

    def test_zero_price(self):
        self.assertEqual(ledger.max_units(price=0, coins=50, weight=0, capacity=135), 0)


if __name__ == "__main__":
    unittest.main()
