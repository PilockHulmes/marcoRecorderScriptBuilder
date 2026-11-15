"""``maplebot.session.TradeSession``：GUI / 控制台共用的会话逻辑。

覆盖点：

- ``update`` 返回 ``State``，字段与 GUI 以前用的完全一致；
- 三级建议优先级：suggest -> buy_trip_plan -> explore_plan（前一级有结果就不查
  下一级）；
- 关掉商店会清空滚动合并缓冲（再开另一家店不会带上一家的价格）；
- ``gui.Controller`` / ``runtime.Runtime`` 都只是这个共享会话的视图。
"""

import contextlib
import unittest
from unittest import mock

import numpy as np

from maplebot import advice as advice_module
from maplebot import gui
from maplebot import runtime as runtime_module
from maplebot import session as session_module
from maplebot import shop


def make_row(good_id, side, price):
    return shop.Row(good_id, good_id, side, price)


class SessionStateTest(unittest.TestCase):
    def setUp(self):
        self.ledger = mock.Mock()
        self.ledger.record = lambda visit, now=None: None
        self.ledger.load.return_value = []
        self.ledger.valid_until = lambda observation: 0
        self.watcher = mock.Mock()
        self.watcher.last_map_obs = mock.Mock(map_id="A")
        self.session = session_module.TradeSession(
            watcher=self.watcher, ledger=self.ledger,
            travel=advice_module.MapTravel(graph={}, edge_times=[]))
        self.frame = np.zeros((8, 8, 3), np.uint8)

    def _visit(self):
        visit = shop.Visit(map="A", merchant="石铁", kind="fixed", refresh_in=120,
                           coins=50, weight=0, capacity=135)
        visit.rows = [make_row("g", "sell", 10)]
        return visit

    def test_update_returns_state(self):
        with mock.patch.object(session_module.trade, "find_shop_window",
                               return_value=False), \
                mock.patch.object(session_module.trade, "find_cargo_window",
                                  return_value=False):
            state = self.session.update(self.frame, now=3.0)
        self.assertIsInstance(state, session_module.State)
        self.assertEqual(state.map, "A")
        self.assertEqual(state.advice, [])
        self.assertEqual(state.cargo, [])
        self.assertTrue(state.board)             # 固定商人看板照常生成

    def test_update_default_records_wall_clock(self):
        """生产路径（不传 now）落盘必须是墙钟，monotonic 只在内部做节流。"""
        book = mock.Mock()
        book.load.return_value = []
        book.valid_until = lambda observation: 0
        session = session_module.TradeSession(
            watcher=mock.Mock(last_map_obs=mock.Mock(map_id="A")),
            ledger=book, travel=advice_module.MapTravel(graph={}, edge_times=[]))
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                session_module.trade, "find_shop_window", return_value=True))
            stack.enter_context(mock.patch.object(
                shop, "read_visit", return_value=self._visit()))
            stack.enter_context(mock.patch.object(
                advice_module, "suggest", return_value=[]))
            stack.enter_context(mock.patch.object(
                advice_module, "buy_trip_plan", return_value=[]))
            stack.enter_context(mock.patch.object(
                advice_module, "explore_plan", return_value=[]))
            session.update(self.frame)          # 不传 now：和 GUI / 控制台一样
        used = book.record.call_args.kwargs["now"]
        self.assertGreaterEqual(used, 1_000_000_000)

    def test_advice_priority_suggest_wins(self):
        suggestion = advice_module.Suggestion(
            good_id="g", good="桔梗", buy_at="A", buy_price=10, units=1,
            sell_at="B", sell_price=20, hops=1, seconds=60,
            profit_per_unit=10, profit_total=10, reason="test")
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                session_module.trade, "find_shop_window", return_value=True))
            stack.enter_context(mock.patch.object(
                shop, "read_visit", return_value=self._visit()))
            stack.enter_context(mock.patch.object(
                advice_module, "suggest", return_value=[suggestion]))
            trips = stack.enter_context(mock.patch.object(
                advice_module, "buy_trip_plan"))
            explore = stack.enter_context(mock.patch.object(
                advice_module, "explore_plan"))
            state = self.session.update(self.frame, now=1.0)
        self.assertIn("B 賣", " ".join(state.advice))
        trips.assert_not_called()
        explore.assert_not_called()

    def test_advice_priority_buy_trip_before_explore(self):
        trip = {"merchant": "石鉄", "good": "桔梗", "price": 13,
                "hops": 2, "left": 150.0}
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                session_module.trade, "find_shop_window", return_value=True))
            stack.enter_context(mock.patch.object(
                shop, "read_visit", return_value=self._visit()))
            stack.enter_context(mock.patch.object(
                advice_module, "suggest", return_value=[]))
            stack.enter_context(mock.patch.object(
                advice_module, "buy_trip_plan", return_value=[trip]))
            explore = stack.enter_context(mock.patch.object(
                advice_module, "explore_plan"))
            state = self.session.update(self.frame, now=1.0)
        self.assertEqual(state.advice,
                         ["去 石鉄",
                          "  買 桔梗 @13 距离 2 张图　到了还剩 2:30"])
        explore.assert_not_called()

    def test_advice_falls_back_to_explore(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                session_module.trade, "find_shop_window", return_value=True))
            stack.enter_context(mock.patch.object(
                shop, "read_visit", return_value=self._visit()))
            stack.enter_context(mock.patch.object(
                advice_module, "suggest", return_value=[]))
            stack.enter_context(mock.patch.object(
                advice_module, "buy_trip_plan", return_value=[]))
            stack.enter_context(mock.patch.object(
                advice_module, "explore_plan",
                return_value=[{"merchant": "瑪帕", "map": "B", "hops": 2}]))
            state = self.session.update(self.frame, now=1.0)
        self.assertEqual(state.advice, ["去看看 瑪帕（B） 距离 2 张图"])


class ShopMergeResetTest(unittest.TestCase):
    """关窗清空滚动合并缓冲：换一家店不能带上上一家的价格。"""

    def setUp(self):
        self.ledger = mock.Mock()
        self.ledger.load.return_value = []
        self.ledger.valid_until = lambda observation: 0
        self.watcher = mock.Mock()
        self.watcher.last_map_obs = mock.Mock(map_id="A")
        self.session = session_module.TradeSession(
            watcher=self.watcher, ledger=self.ledger,
            travel=advice_module.MapTravel(graph={}, edge_times=[]))
        self.frame = np.zeros((8, 8, 3), np.uint8)

    @staticmethod
    def _visit(rows):
        visit = shop.Visit(map="A", merchant="石铁", kind="fixed", refresh_in=300,
                           coins=50, weight=0, capacity=135)
        visit.rows = list(rows)
        return visit

    def test_closing_shop_clears_merged(self):
        visits = [self._visit([make_row("g1", "sell", 10)]),
                  self._visit([make_row("g2", "buy", 20)])]
        opens = [True, False, True]
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                shop, "read_visit", side_effect=visits))
            stack.enter_context(mock.patch.object(
                advice_module, "suggest", return_value=[]))
            stack.enter_context(mock.patch.object(
                session_module.trade, "find_cargo_window", return_value=False))
            stack.enter_context(mock.patch.object(
                session_module.trade, "find_shop_window", side_effect=opens))
            self.session.update(self.frame, now=100.0)
            self.assertEqual(self.session._merged.keys(), {("g1", "sell")})
            self.session.update(self.frame, now=100.5)     # 关窗
            self.assertEqual(self.session._merged, {})
            self.session.update(self.frame, now=101.0)     # 另一家店
        self.assertEqual(self.session._merged.keys(), {("g2", "buy")})
        calls = self.ledger.record.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual({(row.good_id, row.side) for row in calls[-1].args[0].rows},
                         {("g2", "buy")})


class SharedViewTest(unittest.TestCase):
    """GUI / 控制台都只是视图，不再有各自的商店读取实现。"""

    def test_controller_is_thin_session_subclass(self):
        self.assertTrue(issubclass(gui.Controller, session_module.TradeSession))
        self.assertIs(gui.Controller.update, session_module.TradeSession.update)

    def test_runtime_uses_trade_session(self):
        runtime = runtime_module.Runtime(
            watcher=mock.Mock(last_map_obs=mock.Mock(map_id="A")),
            ledger=mock.Mock(), travel=advice_module.MapTravel(graph={},
                                                               edge_times=[]))
        self.assertIsInstance(runtime.session, session_module.TradeSession)


if __name__ == "__main__":
    unittest.main()
