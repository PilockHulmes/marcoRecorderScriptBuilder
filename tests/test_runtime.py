import unittest
from unittest import mock

import numpy as np

from maplebot import advice as advice_module
from maplebot import ledger as ledger_module
from maplebot import runtime as runtime_module
from maplebot import shop


class _Row:
    def __init__(self, good_id, name, side, price):
        self.good_id = good_id
        self.good_name = name
        self.side = side
        self.price = price


def make_visit(map_name="A", merchant="石铁", rows=(), coins=50, weight=0):
    visit = shop.Visit(map=map_name, merchant=merchant, kind="fixed",
                       refresh_in=300, coins=coins, weight=weight, capacity=135)
    visit.rows = list(rows)
    return visit


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        self.ledger = ledger_module.Ledger(":memory:")   # 不会真的写盘
        self.ledger.record = lambda visit, now=None: visit.to_dict()
        self.watcher = mock.Mock()
        self.watcher.last_map_obs = mock.Mock(map_id="A")
        self.runtime = runtime_module.Runtime(watcher=self.watcher, ledger=self.ledger,
                                              travel=advice_module.MapTravel(graph={}), )
        self.frame = np.zeros((10, 10, 3), np.uint8)

    def test_closed_shop_says_nothing(self):
        with mock.patch.object(runtime_module, "shop_open", return_value=False):
            self.assertEqual(self.runtime.step(self.frame, now=0.0), [])

    def test_open_records_once_then_throttles(self):
        visit = make_visit(rows=[_Row("g", "货", "sell", 10)])
        calls = []
        with mock.patch.object(runtime_module, "shop_open", return_value=True), \
                mock.patch.object(shop, "read_visit", side_effect=lambda f, m: visit), \
                mock.patch.object(advice_module, "suggest", return_value=[]), \
                mock.patch.object(runtime_module.Runtime, "_remaining_seconds",
                                  return_value=None), \
                mock.patch.object(self.ledger, "record",
                                  side_effect=lambda v, now=None: calls.append(v)):
            self.runtime.step(self.frame, now=0.0)      # 第一次：记录
            self.runtime.step(self.frame, now=0.5)      # 节流内：不记录
            self.runtime.step(self.frame, now=5.0)      # 超过 advice_every：不重复记录
        self.assertEqual(len(calls), 1)

    def test_close_then_open_records_again(self):
        visit = make_visit()
        calls = []
        with mock.patch.object(runtime_module, "shop_open", return_value=True), \
                mock.patch.object(shop, "read_visit", side_effect=lambda f, m: visit), \
                mock.patch.object(advice_module, "suggest", return_value=[]), \
                mock.patch.object(runtime_module.Runtime, "_remaining_seconds",
                                  return_value=None), \
                mock.patch.object(self.ledger, "record",
                                  side_effect=lambda v, now=None: calls.append(v)):
            self.runtime.step(self.frame, now=0.0)
        with mock.patch.object(runtime_module, "shop_open", return_value=False):
            self.runtime.step(self.frame, now=1.0)
        with mock.patch.object(runtime_module, "shop_open", return_value=True), \
                mock.patch.object(shop, "read_visit", side_effect=lambda f, m: visit), \
                mock.patch.object(advice_module, "suggest", return_value=[]), \
                mock.patch.object(runtime_module.Runtime, "_remaining_seconds",
                                  return_value=None), \
                mock.patch.object(self.ledger, "record",
                                  side_effect=lambda v, now=None: calls.append(v)):
            self.runtime.step(self.frame, now=2.0)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
