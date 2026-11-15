import json
import tempfile
import time
import unittest
from pathlib import Path

from maplebot import ledger

#: 合成时间轴一律用墙钟数量级，避免被 Ledger 的 monotonic 防护改写。
BASE = 1_700_000_000.0


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
        self.ledger.record(visit("A", "甲", [("honey", "buy", 50)]), now=BASE)
        self.assertEqual(len(self.ledger.load()), 1)

    def test_record_with_monotonic_now_saves_wall_clock(self):
        """旧调用方传 monotonic（12345）时，实际落盘必须是墙钟。"""
        payload = self.ledger.record(visit("A", "甲", [("honey", "buy", 50)]),
                                     now=12345)
        self.assertGreaterEqual(payload["t"], ledger.MIN_WALL_CLOCK)
        saved = self.ledger.load()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["t"], payload["t"])
        self.assertGreaterEqual(saved[0]["t"], ledger.MIN_WALL_CLOCK)

    def test_default_valid_uses_wall_clock(self):
        self.ledger.record(visit("A", "甲", [("honey", "buy", 50)]), now=time.time())
        self.assertEqual([o["map"] for o in self.ledger.valid()], ["A"])

    def test_load_skips_legacy_monotonic_observations(self):
        """上一次开机落盘的 t=61665 这类记录跨进程无意义，读的时候直接跳过。"""
        legacy = visit("A", "甲", [("honey", "buy", 50)])
        legacy["t"] = 61665.078
        wall = visit("B", "乙", [("silk", "sell", 20)])
        wall["t"] = BASE
        self.ledger.path.write_text(
            json.dumps(legacy, ensure_ascii=False) + "\n"
            + json.dumps(wall, ensure_ascii=False) + "\n",
            encoding="utf-8")
        self.assertEqual([o["map"] for o in self.ledger.load()], ["B"])

    def test_best_bid_picks_highest(self):
        self.ledger.record(visit("A", "甲", [("honey", "buy", 50)]), now=BASE)
        self.ledger.record(visit("B", "乙", [("honey", "buy", 80)]), now=BASE + 10)
        best = self.ledger.best_bid("honey", at=BASE + 20)
        self.assertEqual(best["price"], 80)
        self.assertEqual(best["map"], "B")

    def test_expired_observation_ignored(self):
        self.ledger.record(visit("A", "甲", [("honey", "buy", 50)], refresh=30), now=BASE)
        self.assertIsNotNone(self.ledger.best_bid("honey", at=BASE + 20))
        self.assertIsNone(self.ledger.best_bid("honey", at=BASE + 40))

    def test_arrival_time_check(self):
        """现在有效、但 25 秒后（走到了）已过期 -> 不能推荐。"""
        self.ledger.record(visit("A", "甲", [("honey", "buy", 50)], refresh=30), now=BASE)
        self.assertIsNone(self.ledger.best_bid("honey", at=BASE + 35))

    def test_offers_only_sell_side(self):
        self.ledger.record(visit("A", "甲", [("honey", "buy", 50), ("silk", "sell", 20)]),
                           now=BASE)
        offers = self.ledger.offers(at=BASE + 10)
        self.assertEqual([o["good_id"] for o in offers], ["silk"])

    def test_exclude_current_map(self):
        self.ledger.record(visit("A", "甲", [("honey", "buy", 50)]), now=BASE)
        self.assertIsNone(self.ledger.best_bid("honey", at=BASE + 10, exclude_map="A"))


class MaxUnitsTest(unittest.TestCase):
    def test_limited_by_coins(self):
        self.assertEqual(ledger.max_units(price=13, coins=50, weight=0, capacity=135), 3)

    def test_limited_by_room(self):
        self.assertEqual(ledger.max_units(price=1, coins=1000, weight=130, capacity=135), 5)

    def test_zero_price(self):
        self.assertEqual(ledger.max_units(price=0, coins=50, weight=0, capacity=135), 0)


if __name__ == "__main__":
    unittest.main()
