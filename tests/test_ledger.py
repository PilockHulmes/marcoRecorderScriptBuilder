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

class CountdownTest(unittest.TestCase):
    """倒计时必须随真实时间递减，不能被"最大剩余时间 + 推进 t"钉住。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = ledger.Ledger(Path(self.tmp.name) / "obs.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _visit(self, refresh, price=15, good="ore_shard"):
        return {"map": "M", "merchant_id": "kobi_2", "merchant": "奇里營",
                "merchant_kind": "fixed", "refresh_in": refresh,
                "rows": [{"good_id": good, "good": good, "side": "sell",
                          "price": price}]}

    def _deadline(self):
        return max(item["deadline"] for item in self.ledger.load())

    def test_countdown_follows_the_clock_not_the_first_reading(self):
        self.ledger.record(self._visit(238), now=BASE)
        self.ledger.record(self._visit(208), now=BASE + 30)
        self.ledger.record(self._visit(178), now=BASE + 60)
        self.assertAlmostEqual(self._deadline() - BASE, 238, delta=1.5)
        remaining = self._deadline() - (BASE + 60)
        self.assertAlmostEqual(remaining, 178, delta=1.5)

    def test_same_shop_does_not_create_extra_cycles(self):
        for offset, refresh in ((0, 238), (30, 208), (60, 178)):
            self.ledger.record(self._visit(refresh), now=BASE + offset)
        self.assertEqual(len(self.ledger.load()), 1)

    def test_new_shop_session_creates_a_new_cycle(self):
        self.ledger.record(self._visit(20, price=15), now=BASE)
        self.ledger.record(self._visit(238, price=99), now=BASE + 22)
        deadlines = sorted(item["deadline"] - BASE for item in self.ledger.load())
        self.assertEqual(len(deadlines), 2)
        self.assertAlmostEqual(deadlines[0], 20, delta=1.5)
        self.assertAlmostEqual(deadlines[1], 260, delta=1.5)

    def test_missing_countdown_keeps_the_current_cycle(self):
        self.ledger.record(self._visit(200), now=BASE)
        self.ledger.record(self._visit(0, price=42), now=BASE + 30)
        self.assertEqual(len(self.ledger.load()), 1)
        self.assertAlmostEqual(self._deadline() - BASE, 200, delta=1.5)

    def test_exported_row_uses_the_remaining_at_observation_time(self):
        self.ledger.record(self._visit(238), now=BASE)
        self.ledger.record(self._visit(178, price=17), now=BASE + 60)
        record = self.ledger.merchant_record("kobi_2")
        row = record["rows"]["ore_shard|sell"]
        self.assertEqual(row["p"], 17)
        self.assertAlmostEqual(row["r"], 178, delta=1.5)

    def test_remote_rows_keep_their_own_deadline(self):
        record = {"merchant_id": "kobi_1", "map": "M", "writer": "peer", "rev": 1,
                  "rows": {"natural_honey|sell": {"p": 64, "t": BASE - 60, "r": 200}}}
        self.ledger.apply_remote("kobi_1", record)
        item = [o for o in self.ledger.load() if o["merchant_id"] == "kobi_1"][0]
        self.assertAlmostEqual(self.ledger.valid_until(item) - BASE, 140, delta=1.5)

    def test_legacy_cycle_without_deadline_still_works(self):
        legacy = {"merchants": {"kobi_1": {"id": "kobi_1", "map": "M",
                                           "merchant": "石鐵", "kind": "fixed",
                                           "cycles": {"1700000100": {
                                               "t": BASE, "refresh_in": 100,
                                               "rows": {"honey|sell": {
                                                   "p": 64, "t": BASE, "r": 100,
                                                   "src": "local"}}}}}}}
        path = Path(self.tmp.name) / "legacy.json"
        path.write_text(json.dumps(legacy), encoding="utf-8")
        book = ledger.Ledger(path)
        item = book.load()[0]
        self.assertTrue(path.exists())
        self.assertAlmostEqual(book.valid_until(item), BASE + 100, delta=0.5)

