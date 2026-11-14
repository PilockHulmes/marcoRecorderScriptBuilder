import unittest
from unittest import mock

import numpy as np

from maplebot import advice as advice_module
from maplebot import ledger as ledger_module
from maplebot import runtime as runtime_module
from maplebot import shop


def row(good_id, side, price):
    return shop.Row(good_id, good_id, side, price)


def visit(rows):
    v = shop.Visit(map="A", merchant="石铁", kind="fixed", refresh_in=300,
                   coins=50, weight=0, capacity=135)
    v.rows = list(rows)
    return v


class ScrollMergeTest(unittest.TestCase):
    def test_rows_merge_across_frames(self):
        ledger = mock.Mock()
        watcher = mock.Mock()
        watcher.last_map_obs = mock.Mock(map_id="A")
        rt = runtime_module.Runtime(watcher=watcher, ledger=ledger,
                                    travel=advice_module.MapTravel(graph={}, edge_times=[]),
                                    advice_every=0.0)
        frames = [
            visit([row("g1", "sell", 10)]),
            visit([row("g2", "sell", 20), row("g3", "buy", 30)]),   # 滚动后
        ]
        with mock.patch.object(runtime_module, "shop_open", return_value=True), \
                mock.patch.object(shop, "read_visit", side_effect=frames), \
                mock.patch.object(advice_module, "suggest", return_value=[]), \
                mock.patch.object(runtime_module.Runtime, "_remaining_seconds",
                                  return_value=None):
            rt.step(np.zeros((4, 4, 3), np.uint8), now=0.0)
            rt.step(np.zeros((4, 4, 3), np.uint8), now=1.0)

        # 最后一次写入应含三件货（跨两帧累积）
        last = ledger.record.call_args_list[-1][0][0]
        goods = {(r.good_id, r.side) for r in last.rows}
        self.assertEqual(goods, {("g1", "sell"), ("g2", "sell"), ("g3", "buy")})

        # 第一次写入只有第一帧的货
        first = ledger.record.call_args_list[0][0][0]
        self.assertEqual({(r.good_id, r.side) for r in first.rows}, {("g1", "sell")})


if __name__ == "__main__":
    unittest.main()
