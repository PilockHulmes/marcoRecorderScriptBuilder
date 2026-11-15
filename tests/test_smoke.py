"""冒烟测试：用**真实截图**跑完整流水线（不联网、不启动游戏）。

单元测试全是 mock，抓不到"真实画面读错"这类问题（金币读成 0、货舱读不到、坐标偏
25 像素）。这里用 ``tests/fixtures/`` 里的两帧真实截图，覆盖：

1. 读图：商店窗口 → 商人/价格/金币/负重/货物数量；
2. 会话：``TradeSession.update`` 跑完整条链，建议里不许出现"失败"；
3. 布局：``layout_board`` 出 15 个商人且不越界；
4. 界面：``View`` 建控件 → 画一次 → 销毁。
"""

import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

from maplebot import advice as advice_module
from maplebot import gui
from maplebot import session as session_module
from maplebot import shop
from maplebot import trade

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SHOP_FRAME = FIXTURES / "shop_frame.png"
CARGO_FRAME = FIXTURES / "cargo_frame.png"


def load(path):
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


@unittest.skipUnless(SHOP_FRAME.exists(), "缺少 tests/fixtures/shop_frame.png")
class ReadPipelineSmokeTest(unittest.TestCase):
    """真实商店截图：窗口检测、商品行、金币/负重、身上的货。"""

    @classmethod
    def setUpClass(cls):
        cls.frame = load(SHOP_FRAME)

    def test_window_detected(self):
        self.assertTrue(trade.find_shop_window(self.frame))

    def test_visit_reads_merchant_and_rows(self):
        visit = shop.read_visit(self.frame, "孤獨的沙漠-2",
                                learn_names=False, learn_icons=False)
        self.assertEqual(visit.merchant, "幹員 0")
        self.assertEqual(len(visit.rows), 3)
        prices = {row.good_name: (row.side, row.price) for row in visit.rows}
        self.assertEqual(prices["矿石碎片"], ("sell", 12))
        self.assertEqual(prices["蓝宝石碎片"], ("sell", 40))
        self.assertEqual(prices["猪肉"], ("buy", 13))

    def test_cargo_numbers(self):
        cargo = trade.read_cargo(self.frame, profile="shop")
        self.assertEqual((cargo.coins, cargo.weight, cargo.capacity), (0, 5, 135))

    def test_carried_goods_with_counts(self):
        held = shop.read_cargo_items(self.frame, profile="shop", with_counts=True)
        self.assertEqual(held, [("ore_shard", 5)])


@unittest.skipUnless(CARGO_FRAME.exists(), "缺少 tests/fixtures/cargo_frame.png")
class CargoOnlySmokeTest(unittest.TestCase):
    """只开货舱：窗口检测 + 货物识别。"""

    def test_cargo_window_and_items(self):
        frame = load(CARGO_FRAME)
        self.assertTrue(trade.find_cargo_window(frame))
        self.assertFalse(trade.find_shop_window(frame))
        self.assertEqual(shop.read_cargo_items(frame), ["balloon_flower"])


class SessionSmokeTest(unittest.TestCase):
    """会话跑完整条链：不崩、有建议、没有"失败"字样。"""

    def test_update_on_real_frame(self):
        frame = load(SHOP_FRAME)
        session = session_module.TradeSession()
        session.current_map = lambda: "孤獨的沙漠-2"
        with mock.patch.object(session_module.shop, "read_cargo_items",
                               return_value=[("ore_shard", 5)]):
            state = session.update(frame, now=1_700_000_000.0)
        self.assertEqual(state.map, "孤獨的沙漠-2")
        self.assertTrue(state.board)
        self.assertNotIn("失败", " ".join(state.advice))
        # 这一帧的矿石碎片 12 ≤ 一类阈值，所以走"买"的分支（不读身上的货）
        self.assertTrue(state.advice)
        self.assertIn("矿石碎片", " ".join(state.advice))


class BoardSmokeTest(unittest.TestCase):
    def test_board_layout_has_fifteen_merchants(self):
        session = session_module.TradeSession()
        session.current_map = lambda: "孤獨的沙漠-2"
        frame = load(SHOP_FRAME)
        state = session.update(frame, now=1_700_000_000.0)
        layout = gui.layout_board(state.board, 1080)
        self.assertEqual(layout.columns, 3)
        owners = {item.owner for item in layout.of_kind("merchant")}
        self.assertEqual(len(owners), 15)
        for item in layout.items:
            self.assertGreaterEqual(item.x, 0)
            self.assertLessEqual(item.x + item.w, layout.width + 1)


class ViewSmokeTest(unittest.TestCase):
    """建控件 → 画一次 → 销毁；不进 mainloop、不启动后台线程。"""

    def test_build_and_paint(self):
        try:
            import tkinter as tk
        except Exception:                       # pragma: no cover
            self.skipTest("没有 Tk")
        try:
            root = tk.Tk()
        except Exception:                       # pragma: no cover
            self.skipTest("没有可用显示环境")
        try:
            root.withdraw()
            view = gui.View(root)
            state = session_module.State(map="孤獨的沙漠-2")
            state.stats = {"coins": 172, "weight": 5, "capacity": 135}
            state.goods = [("矿石碎片", 5)]
            state.blocks = [["矿石碎片 → 寇比（通往古代遺跡的路），距离 4 张图"]]
            state.board = []
            view.paint(state)
            self.assertIn("孤獨的沙漠-2", view.header.cget("text"))
            self.assertIn("矿石碎片×5", view.header.cget("text"))
            self.assertIn("寇比", view.advice_box.get("1.0", "end-1c"))
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
