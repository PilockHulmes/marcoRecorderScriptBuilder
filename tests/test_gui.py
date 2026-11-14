import unittest
from unittest import mock

import numpy as np

from maplebot import advice as advice_module
from maplebot import gui
from maplebot import shop


def make_row(good_id, side, price):
    return shop.Row(good_id, good_id, side, price)


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self.ledger = mock.Mock()
        self.ledger.record = lambda visit, now=None: None
        self.ledger.load.return_value = []
        self.ledger.valid_until = lambda observation: 0
        self.watcher = mock.Mock()
        self.watcher.last_map_obs = mock.Mock(map_id="A")
        self.controller = gui.Controller(watcher=self.watcher, ledger=self.ledger,
                                         travel=advice_module.MapTravel(graph={}, edge_times=[]))
        self.frame = np.zeros((8, 8, 3), np.uint8)

    def test_no_windows_no_advice(self):
        with mock.patch.object(gui.trade, "find_shop_window", return_value=False), \
                mock.patch.object(gui.trade, "find_cargo_window", return_value=False):
            state = self.controller.update(self.frame, now=1.0)
        self.assertEqual(state.advice, [])
        self.assertEqual(state.cargo, [])
        self.assertEqual(state.map, "A")

    def test_shop_advice_appears(self):
        visit = shop.Visit(map="A", merchant="石铁", kind="fixed", refresh_in=120,
                           coins=50, weight=0, capacity=135)
        visit.rows = [make_row("g", "sell", 10)]
        with mock.patch.object(gui.trade, "find_shop_window", return_value=True), \
                mock.patch.object(shop, "read_visit", return_value=visit), \
                mock.patch.object(advice_module, "suggest", return_value=[]), \
                mock.patch.object(advice_module, "explore_plan", return_value=[]):
            state = self.controller.update(self.frame, now=1.0)
        self.assertTrue(state.advice)          # 没有生意时至少有一行提示

    def test_shop_throttled(self):
        visit = shop.Visit(map="A", merchant="石铁", kind="fixed", refresh_in=120,
                           coins=50, weight=0, capacity=135)
        visit.rows = [make_row("g", "sell", 10)]
        calls = []
        with mock.patch.object(gui.trade, "find_shop_window", return_value=True), \
                mock.patch.object(shop, "read_visit",
                                  side_effect=lambda f, m: calls.append(1) or visit), \
                mock.patch.object(advice_module, "suggest", return_value=[]), \
                mock.patch.object(advice_module, "explore_plan", return_value=[]):
            self.controller.update(self.frame, now=1.0)     # 打开：立刻读
            self.controller.update(self.frame, now=1.1)     # 节流内：不读
            self.controller.update(self.frame, now=1.5)     # 超过 0.4s：读
        self.assertEqual(len(calls), 2)

    def test_cargo_runs_when_no_shop(self):
        with mock.patch.object(gui.trade, "find_shop_window", return_value=False), \
                mock.patch.object(gui.trade, "find_cargo_window", return_value=True), \
                mock.patch.object(shop, "read_cargo_items", return_value=["g"]), \
                mock.patch.object(advice_module, "sell_plan", return_value=[]):
            state = self.controller.update(self.frame, now=1.0)
        self.assertTrue(state.cargo)

    def test_board_carries_merchant_and_good_ids(self):
        """看板要带 merchant_id / good_id 才能画头像和商品图标。"""
        self.ledger.load.return_value = [{
            "merchant": "石铁", "merchant_id": "dour_4", "map": "A",
            "refresh_in": 120, "t": 1.0,
            "rows": [{"good_id": "pork", "good": "猪肉", "side": "sell", "price": 10}],
        }]
        self.ledger.valid_until = lambda observation: 121.0
        with mock.patch.object(gui.trade, "find_shop_window", return_value=False), \
                mock.patch.object(gui.trade, "find_cargo_window", return_value=False):
            state = self.controller.update(self.frame, now=3.0)
        self.assertEqual(len(state.board), 1)
        entry = state.board[0]
        self.assertEqual(entry["merchant_id"], "dour_4")
        self.assertEqual(entry["until"], 121.0)
        self.assertEqual(entry["rows"][0]["good_id"], "pork")

    def test_board_merchant_id_falls_back_to_map(self):
        """老记录没有 merchant_id 时按地图反查。"""
        self.ledger.load.return_value = [{
            "merchant": "史莱", "map": "A", "refresh_in": 60, "t": 1.0, "rows": [],
        }]
        self.ledger.valid_until = lambda observation: 61.0
        with mock.patch.object(gui.trade, "find_shop_window", return_value=False), \
                mock.patch.object(gui.trade, "find_cargo_window", return_value=False), \
                mock.patch.object(gui.shop, "load_merchant_maps",
                                  return_value={"A": {"merchant_id": "dour_4"}}):
            state = self.controller.update(self.frame, now=3.0)
        self.assertEqual(state.board[0]["merchant_id"], "dour_4")


class StatusColorTest(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(gui.status_color(61), gui.COLOR_GREEN)
        self.assertEqual(gui.status_color(60), gui.COLOR_YELLOW)
        self.assertEqual(gui.status_color(0), gui.COLOR_GRAY)
        self.assertEqual(gui.status_color(-5), gui.COLOR_GRAY)


class IconKeyTest(unittest.TestCase):
    def test_rejects_path_traversal(self):
        self.assertTrue(gui._valid_key("pork"))
        self.assertFalse(gui._valid_key(""))
        self.assertFalse(gui._valid_key("../pork"))
        self.assertFalse(gui._valid_key("icons/pork"))
        self.assertFalse(gui._valid_key(None))


if __name__ == "__main__":
    unittest.main()
