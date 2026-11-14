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


if __name__ == "__main__":
    unittest.main()
