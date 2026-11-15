"""建议分支矩阵：``_read_shop`` 的四种情况各跑一次。

为什么单独写这一组：以前只测"函数返回什么"，`sell_plan` 在测试里被写死返回空，
于是"有货、有买家、生成卖货建议"这条分支**从没被执行过**，里面一个未定义函数
（``_sell_line``）就能让程序在运行时直接崩，而 585 个用例照样全绿。
"""

import unittest
from unittest import mock

import numpy as np

from maplebot import advice as advice_module
from maplebot import session as session_module
from maplebot import shop


def visit_with(rows, coins=50):
    visit = shop.Visit(map="A", merchant="石铁", kind="fixed", refresh_in=120,
                       coins=coins, weight=0, capacity=135)
    visit.rows = [shop.Row(g, g, side, price) for g, side, price in rows]
    return visit


class AdviceBranchTest(unittest.TestCase):
    def setUp(self):
        self.ledger = mock.Mock()
        self.ledger.record = lambda v, now=None: None
        self.ledger.load.return_value = []
        self.ledger.valid_until = lambda observation: 0
        self.watcher = mock.Mock()
        self.watcher.last_map_obs = mock.Mock(map_id="A")
        self.session = session_module.TradeSession(
            watcher=self.watcher, ledger=self.ledger,
            travel=advice_module.MapTravel(graph={}, edge_times=[]))
        self.frame = np.zeros((8, 8, 3), np.uint8)
        self.visit = visit_with([("g", "sell", 10)])

    def _run(self, suggest=(), held=(), sell=(), trips=(), explore=()):
        with mock.patch.object(session_module.trade, "find_shop_window",
                               return_value=True), \
                mock.patch.object(shop, "read_visit", return_value=self.visit), \
                mock.patch.object(shop, "read_cargo_items", return_value=list(held)), \
                mock.patch.object(advice_module, "suggest", return_value=list(suggest)), \
                mock.patch.object(advice_module, "sell_plan", return_value=list(sell)), \
                mock.patch.object(advice_module, "buy_trip_plan", return_value=list(trips)), \
                mock.patch.object(advice_module, "explore_plan", return_value=list(explore)):
            state = self.session.update(self.frame, now=1.0)
        return state

    def test_branch_buy(self):
        suggestion = advice_module.Suggestion(
            good_id="g", good="桔梗", buy_at="石铁", buy_price=10, units=5,
            sell_at="寇比", sell_price=22, hops=4, seconds=240,
            profit_per_unit=12, profit_total=60, reason="test",
            buy_map="A", sell_map="B")
        state = self._run(suggest=[suggestion])
        joined = " ".join(state.advice)
        self.assertIn("桔梗", joined)
        self.assertIn("寇比", joined)

    def test_branch_sell_held_goods(self):
        """有货、有买家：必须走卖货分支（这条以前完全没被覆盖）。"""
        plan = [{"good": "矿石碎片", "merchant": "寇比",
                 "map": "通往古代遺跡的路", "price": None, "hops": 4}]
        state = self._run(suggest=[], held=["ore_shard"], sell=plan)
        self.assertEqual(state.advice,
                         ["矿石碎片 → 寇比（通往古代遺跡的路），距离 4 张图"])

    def test_branch_sell_with_known_price(self):
        plan = [{"good": "矿石碎片", "merchant": "寇比",
                 "map": "通往古代遺跡的路", "price": 22, "hops": 4}]
        state = self._run(suggest=[], held=["ore_shard"], sell=plan)
        self.assertEqual(state.advice,
                         ["矿石碎片 → 寇比（通往古代遺跡的路） @22，距离 4 张图"])

    def test_branch_buy_trip(self):
        trips = [{"merchant": "石鉄", "map": "豐饒的沙漠-1", "good": "桔梗",
                  "price": 12, "hops": 2, "left": 150.0}]
        state = self._run(suggest=[], held=[], trips=trips)
        joined = " ".join(state.advice)
        self.assertIn("去 石鉄", joined)

    def test_branch_explore(self):
        explore = [{"merchant": "瑪帕", "map": "孤獨的沙漠-3", "hops": 2}]
        state = self._run(suggest=[], held=[], explore=explore)
        self.assertEqual(state.advice, ["去看看 瑪帕（孤獨的沙漠-3） 距离 2 张图"])

    def test_no_held_goods_skips_sell_plan(self):
        """身上没货时不该查卖货，直接落到 trip/explore。"""
        explore = [{"merchant": "瑪帕", "map": "孤獨的沙漠-3", "hops": 2}]
        with mock.patch.object(advice_module, "sell_plan") as sell:
            self._run(suggest=[], held=[], explore=explore)
        sell.assert_not_called()


class FormatterSmokeTest(unittest.TestCase):
    """每个格式化函数各调一次：拼字符串的代码最容易漏名字/写错变量。"""

    def test_sell_line(self):
        self.assertTrue(session_module._sell_line(
            {"good": "矿石碎片", "merchant": "寇比", "price": None, "hops": 4}))
        self.assertIn("@22", session_module._sell_line(
            {"good": "矿石碎片", "merchant": "寇比", "price": 22, "hops": 4}))

    def test_format_suggestions(self):
        item = advice_module.Suggestion(
            good_id="g", good="桔梗", buy_at="石铁", buy_price=10, units=5,
            sell_at="寇比", sell_price=22, hops=4, seconds=240,
            profit_per_unit=12, profit_total=60, reason="test",
            buy_map="A", sell_map="B")
        blocks = advice_module.format_suggestions([item])
        self.assertTrue(blocks and blocks[0])

    def test_format_buy_trips(self):
        blocks = advice_module.format_buy_trips(
            [{"merchant": "石鉄", "map": "M", "good": "桔梗", "price": 12,
              "hops": 2, "left": 150.0}])
        self.assertTrue(blocks and blocks[0])

    def test_format_explore(self):
        blocks = advice_module.format_explore([{"merchant": "瑪帕", "map": "M", "hops": 2}])
        self.assertTrue(blocks and blocks[0])

    def test_format_random_sell(self):
        blocks = advice_module.format_random_sell(
            [{"good": "棉花", "price": 12, "units": 4, "merchant": "寇比",
              "map": "M", "sell_price": 22, "hops": 1, "from_map": "R"}])
        self.assertTrue(blocks and blocks[0])

    def test_format_random_buy(self):
        blocks = advice_module.format_random_buy(
            [{"good": "棉花", "price": 22, "units": 3, "map": "R"}])
        self.assertTrue(blocks and blocks[0])

    def test_empty_placeholders(self):
        self.assertTrue(advice_module.format_suggestions([])[0][0])
        self.assertTrue(advice_module.format_buy_trips([])[0][0])
        self.assertTrue(advice_module.format_explore([])[0][0])
        self.assertTrue(advice_module.format_random_buy([])[0][0])


if __name__ == "__main__":
    unittest.main()

class IdleAdviceTest(unittest.TestCase):
    """什么都没打开时也要给建议（开局/过图后不能空白）。"""

    def setUp(self):
        self.ledger = mock.Mock()
        self.ledger.record = lambda v, now=None: None
        self.ledger.load.return_value = []
        self.ledger.valid_until = lambda observation: 0
        self.watcher = mock.Mock()
        self.watcher.last_map_obs = mock.Mock(map_id="A")
        self.session = session_module.TradeSession(
            watcher=self.watcher, ledger=self.ledger,
            travel=advice_module.MapTravel(graph={"A": ["B"], "B": ["A"]},
                                           edge_times=[]))
        self.frame = np.zeros((8, 8, 3), np.uint8)

    def _update(self):
        with mock.patch.object(session_module.trade, "find_shop_window",
                               return_value=False), \
                mock.patch.object(session_module.trade, "find_cargo_window",
                                  return_value=False), \
                mock.patch.object(advice_module, "_merchant_maps",
                                  return_value={"m1": "B"}), \
                mock.patch.object(advice_module, "_merchant_names",
                                  return_value={"m1": "石鉄"}):
            return self.session.update(self.frame, now=1.0)

    def test_idle_shows_explore_when_no_goods(self):
        state = self._update()
        self.assertEqual(state.advice, ["去看看 石鉄（B） 距离 1 张图"])

    def test_idle_sell_when_carrying_goods(self):
        self.session.held_items = [("g", 3)]
        with mock.patch.object(advice_module, "sell_plan",
                               return_value=[{"good": "矿石碎片", "merchant": "寇比",
                                              "map": "B", "price": None, "hops": 1}]):
            state = self._update()
        self.assertEqual(state.advice, ["矿石碎片 → 寇比（B），距离 1 张图"])

    def test_map_change_does_not_crash(self):
        """过图会触发重算；以前这里调用的是未定义的 _refresh_sell。"""
        self.session.state.map = "A"
        self.session.held_items = [("g", 1)]
        self.watcher.last_map_obs = mock.Mock(map_id="B")
        with mock.patch.object(advice_module, "sell_plan", return_value=[]):
            state = self._update()
        self.assertEqual(state.map, "B")

class NoInternalFailureTest(unittest.TestCase):
    """建议里永远不该出现"计算失败"——那说明异常被 except 吞掉了。"""

    def _session(self):
        ledger = mock.Mock()
        ledger.record = lambda v, now=None: None
        ledger.load.return_value = []
        ledger.valid_until = lambda observation: 0
        watcher = mock.Mock()
        watcher.last_map_obs = mock.Mock(map_id="A")
        return session_module.TradeSession(
            watcher=watcher, ledger=ledger,
            travel=advice_module.MapTravel(graph={"A": ["B"], "B": ["A"]},
                                           edge_times=[]))

    def test_no_failure_text_when_nothing_is_open(self):
        session = self._session()
        frame = np.zeros((8, 8, 3), np.uint8)
        with mock.patch.object(session_module.trade, "find_shop_window",
                               return_value=False), \
                mock.patch.object(session_module.trade, "find_cargo_window",
                                  return_value=False):
            state = session.update(frame, now=1.0)
        self.assertNotIn("失败", " ".join(state.advice))

    def test_no_failure_text_when_shop_errors(self):
        session = self._session()
        frame = np.zeros((8, 8, 3), np.uint8)
        visit = shop.Visit(map="A", merchant="石铁", kind="fixed", refresh_in=120,
                           coins=50, weight=0, capacity=135)
        visit.rows = [shop.Row("g", "g", "sell", 10)]
        with mock.patch.object(session_module.trade, "find_shop_window",
                               return_value=True), \
                mock.patch.object(shop, "read_visit", return_value=visit), \
                mock.patch.object(advice_module, "suggest",
                                  side_effect=RuntimeError("boom")):
            state = session.update(frame, now=1.0)
        # 这里确实会记录失败原因，但必须是明确的一行，而不是静默变成别的建议
        self.assertTrue(any("失败" in line for line in state.advice))
        self.assertEqual(len(state.advice), 1)
