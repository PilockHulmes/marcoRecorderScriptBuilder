import tempfile
import unittest
from pathlib import Path
from unittest import mock

from maplebot import advice, ledger

#: 合成时间轴一律用墙钟数量级，避免被 Ledger 的 monotonic 防护改写。
BASE = 1_700_000_000.0


def visit(map_name, merchant, rows, coins=50, weight=0, refresh=300, merchant_id=""):
    return {"map": map_name, "merchant_id": merchant_id, "merchant": merchant,
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

    def test_edge_times_are_directed(self):
        """A→B 和 B→A 是两条独立的边，不能互相顶替。"""
        graph = {"A": ["B"], "B": ["A"]}
        times = [{"from": "A", "to": "B", "n": 5, "median_fastest": 10.0},
                 {"from": "B", "to": "A", "n": 5, "median_fastest": 30.0}]
        travel = advice.MapTravel(graph=graph, edge_times=times, per_hop=60)
        self.assertEqual(set(travel.times), {("A", "B"), ("B", "A")})
        self.assertAlmostEqual(travel.seconds("A", "B"), 10.0)
        self.assertAlmostEqual(travel.seconds("B", "A"), 30.0)

    def test_missing_direction_uses_default_per_hop(self):
        """只测过 A→B：B→A 仍按默认每跳秒数，不会用正向实测。"""
        graph = {"A": ["B"], "B": ["A"]}
        times = [{"from": "A", "to": "B", "n": 5, "median_fastest": 10.0}]
        travel = advice.MapTravel(graph=graph, edge_times=times, per_hop=60)
        self.assertAlmostEqual(travel.seconds("A", "B"), 10.0)
        self.assertAlmostEqual(travel.seconds("B", "A"), 60.0)

    def test_raw_samples_are_directed(self):
        """运行时原始样本按 (from, to) 分桶：反向样本不参与正向最快 3 次。"""
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw.jsonl"
            rows = ([{"from": "A", "to": "B", "seconds": 10.0}] * 3
                    + [{"from": "B", "to": "A", "seconds": 90.0}] * 3)
            raw.write_text("\n".join(json.dumps(row) for row in rows),
                           encoding="utf-8")
            with mock.patch.object(advice, "EDGE_RAW_PATH", raw):
                travel = advice.MapTravel(graph={"A": ["B"], "B": ["A"]},
                                          edge_times=None, per_hop=60)
        self.assertAlmostEqual(travel.seconds("A", "B"), 10.0)
        self.assertAlmostEqual(travel.seconds("B", "A"), 90.0)


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
        self.ledger.record(visit("甲", "收家", [("g", "buy", 99)], refresh=30), now=BASE)
        current = visit("石铁", "石铁", [("g", "sell", 100)])
        items = module.suggest(_as_visit(current), self.ledger, self.travel, now=BASE)
        self.assertEqual(items, [])

    def test_suggestion_when_window_holds(self):
        from maplebot import advice as module
        module._merchant_maps = lambda: {"kobi_1": "石铁", "buyer": "甲"}
        module._goods = lambda: {"g": {"name": "货", "buyers": ["buyer"]}}
        self.ledger.record(visit("甲", "收家", [("g", "buy", 99)], refresh=600), now=BASE)
        current = visit("石铁", "石铁", [("g", "sell", 10)], coins=50)
        items = module.suggest(_as_visit(current), self.ledger, self.travel, now=BASE)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].profit_per_unit, 89)
        self.assertEqual(items[0].units, 5)      # 50 // 10


class BuyTripPlanTest(unittest.TestCase):
    """别处有便宜货、跑过去还来得及 -> 建议专程去买。"""

    GOODS = {
        "balloon_flower": {"name": "桔梗", "tier": "tier1"},
        "cotton": {"name": "棉花", "tier": "tier2"},
        "potion": {"name": "传说中的补药", "tier": "volatile"},
    }
    NAMES = {"kobi_1": "石鉄", "kobi_3": "藍明"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = ledger.Ledger(Path(self.tmp.name) / "obs.jsonl")
        # here - one(1 跳) - far(2 跳)
        self.graph = {"here": ["one"], "one": ["here", "far"],
                      "far": ["one"]}
        self.travel = advice.MapTravel(graph=self.graph, edge_times=[], per_hop=60)

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, map_name, merchant_id, rows, t=BASE, refresh=300):
        self.ledger.record(
            visit(map_name, self.NAMES.get(merchant_id, merchant_id), rows,
                  refresh=refresh, merchant_id=merchant_id), now=t)

    def plan(self, **kwargs):
        with mock.patch.object(advice, "_goods", return_value=self.GOODS), \
                mock.patch.object(advice, "_merchant_names", return_value=self.NAMES):
            return advice.buy_trip_plan(self.ledger, self.travel, **kwargs)

    def test_cheap_and_reachable(self):
        self.record("one", "kobi_1", [("balloon_flower", "sell", 13)])
        items = self.plan(now=BASE, current_map="here")
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["good"], "桔梗")
        self.assertEqual(item["good_id"], "balloon_flower")
        self.assertEqual(item["price"], 13)
        self.assertEqual(item["merchant"], "石鉄")
        self.assertEqual(item["merchant_id"], "kobi_1")
        self.assertEqual(item["map"], "one")
        self.assertEqual(item["hops"], 1)
        self.assertAlmostEqual(item["seconds"], 60.0)
        self.assertGreater(item["left"], 0)
        self.assertAlmostEqual(item["left"], 240.0)

    def test_expired_before_arrival(self):
        # 报价 30 秒后刷新，但路上要 60 秒 -> 到了已经没了
        self.record("one", "kobi_1", [("balloon_flower", "sell", 13)], refresh=30)
        self.assertEqual(self.plan(now=BASE, current_map="here"), [])

    def test_already_expired_now(self):
        self.record("one", "kobi_1", [("balloon_flower", "sell", 13)], t=BASE, refresh=30)
        self.assertEqual(self.plan(now=BASE + 100, current_map="here"), [])

    def test_price_above_tier_threshold(self):
        self.record("one", "kobi_1", [("balloon_flower", "sell", 14)],
                    refresh=600)
        self.record("one", "kobi_3", [("cotton", "sell", 41)], refresh=600)
        self.assertEqual(self.plan(now=BASE, current_map="here"), [])

    def test_price_at_tier_threshold_is_kept(self):
        self.record("one", "kobi_1", [("balloon_flower", "sell", 13)],
                    refresh=600)
        self.record("one", "kobi_3", [("cotton", "sell", 40)], refresh=600)
        self.assertEqual({item["good_id"] for item in
                          self.plan(now=BASE, current_map="here")},
                         {"balloon_flower", "cotton"})

    def test_volatile_cap(self):
        self.record("one", "kobi_1", [("potion", "sell", 300),
                                      ("balloon_flower", "sell", 301)],
                    refresh=600)
        items = self.plan(now=BASE, current_map="here")
        self.assertEqual([item["good_id"] for item in items], ["potion"])

    def test_quotes_on_current_map_are_excluded(self):
        self.record("here", "kobi_1", [("balloon_flower", "sell", 10)])
        self.assertEqual(self.plan(now=BASE, current_map="here"), [])

    def test_only_sell_rows_are_used(self):
        self.record("one", "kobi_1", [("balloon_flower", "buy", 10)],
                    refresh=600)
        self.assertEqual(self.plan(now=BASE, current_map="here"), [])

    def test_sorted_by_distance_then_price(self):
        self.record("far", "kobi_3", [("balloon_flower", "sell", 9)],
                    refresh=600)
        self.record("one", "kobi_1", [("balloon_flower", "sell", 13)],
                    refresh=600)
        items = self.plan(now=BASE, current_map="here")
        self.assertEqual([item["hops"] for item in items], [1, 2])
        self.assertEqual([item["price"] for item in items], [13, 9])

    def test_same_distance_sorted_by_price(self):
        self.record("one", "kobi_1", [("balloon_flower", "sell", 12)],
                    refresh=600)
        self.record("one", "kobi_3", [("cotton", "sell", 9)], refresh=600)
        items = self.plan(now=BASE, current_map="here")
        self.assertEqual([item["price"] for item in items], [9, 12])

    def test_remaining_time_caps_travel(self):
        self.record("far", "kobi_1", [("balloon_flower", "sell", 13)],
                    refresh=600)
        self.assertEqual(self.plan(now=BASE, current_map="here", remaining=60), [])
        self.assertEqual(len(self.plan(now=BASE, current_map="here", remaining=120)), 1)

    def test_limit(self):
        for merchant_id, map_name in (("kobi_1", "one"), ("kobi_3", "far")):
            self.record(map_name, merchant_id,
                        [("balloon_flower", "sell", 12)], refresh=600)
        self.assertEqual(len(self.plan(now=BASE, current_map="here", limit=1)), 1)

    def test_merchant_name_is_traditional(self):
        """名字要用 merchant_maps.json 的 game_name（石鉄），不是 kobi_1。"""
        self.ledger.record(
            visit("豐饒的沙漠-1", "石铁", [("balloon_flower", "sell", 12)],
                  refresh=600, merchant_id="kobi_1"), now=BASE + 100)
        travel = advice.MapTravel(edge_times=[], per_hop=60)
        with mock.patch.object(advice, "_goods", return_value=self.GOODS):
            items = advice.buy_trip_plan(self.ledger, travel, now=BASE + 100,
                                         current_map="豐饒的沙漠-3")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["merchant"], "石鉄")
        self.assertNotEqual(items[0]["merchant"], "kobi_1")

    def test_format_buy_trips(self):
        item = {"merchant": "石鉄", "good": "桔梗", "price": 13,
                "hops": 2, "left": 150.0}
        self.assertEqual(advice.format_buy_trips([item]),
                         [["去 石鉄",
                           "  買 桔梗 @13",
                           "  距离 2 张图，到了还剩 2:30"]])

    def test_format_buy_trips_uses_map_and_folds_rest(self):
        items = [
            {"merchant": "石鉄", "map": "豐饒的沙漠-1", "good": "桔梗",
             "price": 12, "hops": 2, "left": 150.0},
            {"merchant": "藍明", "map": "豐饒的沙漠-2", "good": "桔梗",
             "price": 13, "hops": 3, "left": 90.0},
        ]
        blocks = advice.format_buy_trips(items)
        self.assertEqual(len(blocks), 2)          # 两列各一条
        self.assertEqual(blocks[0],
                         ["去 石鉄（豐饒的沙漠-1）",
                          "  買 桔梗 @12",
                          "  距离 2 张图，到了还剩 2:30"])
        self.assertEqual(blocks[1][0], "去 藍明（豐饒的沙漠-2）")


class FormatSuggestionsTest(unittest.TestCase):
    """三级建议统一成「动作行 + 物品行 + 结果行」，只展开 top-1。"""

    @staticmethod
    def suggestion(**overrides):
        values = dict(
            good_id="balloon_flower", good="桔梗", buy_at="石鉄",
            buy_price=12, units=3, sell_at="羅森", sell_price=22,
            hops=2, seconds=120, profit_per_unit=10, profit_total=30,
            reason="test", buy_map="豐饒的沙漠-1", sell_map="豐饒的沙漠-3")
        values.update(overrides)
        return advice.Suggestion(**values)

    def test_known_price_is_three_lines(self):
        self.assertEqual(
            advice.format_suggestions([self.suggestion()]),
            [["在 石鉄（豐饒的沙漠-1）",
              "  買 桔梗 @12 × 3 個",
              "  到 羅森 賣 @22，距离 2 张图 赚 30"]])

    def test_unknown_price_result_line_asks_to_check(self):
        item = self.suggestion(price_known=False, sell_price=None,
                               profit_total=0, sell_at="豐饒的沙漠-3",
                               sell_map="")
        self.assertEqual(
            advice.format_suggestions([item]),
            [["在 石鉄（豐饒的沙漠-1）",
              "  買 桔梗 @12 × 3 個",
              "  到 豐饒的沙漠-3 賣，距离 2 张图"]])

    def test_only_top_one_is_expanded(self):
        items = [self.suggestion(), self.suggestion(good="棉花"),
                 self.suggestion(good="蜂蜜")]
        blocks = advice.format_suggestions(items)
        self.assertEqual(len(blocks), 2)          # 两列各一条，折叠由界面负责
        self.assertEqual(advice.fold_text(len(items), len(blocks)), "還有 1 條…")

    def test_fold_line_is_absent_for_single_item(self):
        blocks = advice.format_suggestions([self.suggestion()])
        self.assertEqual(len(blocks), 1)
        self.assertEqual(len(blocks[0]), 3)

    def test_no_items_is_one_placeholder_line(self):
        self.assertEqual(advice.format_suggestions([]), [["（暫無值得跑的建議）"]])

    def test_explore_is_action_plus_distance(self):
        items = [{"merchant": "瑪帕", "map": "B", "hops": 2},
                 {"merchant": "哲利", "map": "C", "hops": 3}]
        blocks = advice.format_explore(items)
        self.assertEqual(blocks[0], ["去看看 瑪帕（B）", "  距离 2 张图"])
        self.assertEqual(len(blocks), 2)
        self.assertEqual(advice.format_explore(items[:1]),
                         [["去看看 瑪帕（B）", "  距离 2 张图"]])


class MerchantNamesTest(unittest.TestCase):
    """名字根因：以前按相对路径读 merchant_maps.json，永远读不到 -> 显示 id。"""

    def test_game_names_from_data_file(self):
        names = advice._merchant_names()
        self.assertEqual(names["kobi_1"], "石鉄")
        self.assertEqual(names["kobi_3"], "藍明")
        self.assertEqual(names["kobi_4"], "瑪帕")

    def test_explore_plan_uses_traditional_names(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        book = ledger.Ledger(Path(tmp.name) / "obs.jsonl")
        travel = advice.MapTravel(edge_times=[], per_hop=60)
        maps = {"石鉄": "豐饒的沙漠-1", "藍明": "豐饒的沙漠-2"}
        with mock.patch.object(advice, "_merchant_maps",
                               return_value={"kobi_1": maps["石鉄"],
                                             "kobi_3": maps["藍明"]}):
            items = advice.explore_plan(book, travel, now=BASE,
                                        current_map="豐饒的沙漠-3")
        names = {item["merchant_id"]: item["merchant"] for item in items}
        self.assertEqual(names["kobi_1"], "石鉄")
        self.assertEqual(names["kobi_3"], "藍明")
        self.assertNotIn("kobi_1", names.values())


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
