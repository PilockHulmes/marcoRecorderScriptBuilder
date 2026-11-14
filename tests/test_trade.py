"""maplebot.trade 的读图测试：用三张真实跑商截图当 fixture。

截图在 ``screenshots/trading/``（已 gitignore）。图片不存在或没装 PaddleOCR 时
整类 skip，不会让「没截图的机器」挂掉。

覆盖：窗口检测、行数、买/卖价、CARGO、滚动条顶部/底部、partial 行、CLI JSON。
"""

import importlib.util
import json
import os
import subprocess
import sys
import unittest

from maplebot import trade
from tests.helpers import ROOT

TRADING = ROOT / "screenshots" / "trading"
TOP = TRADING / "UI示例.png"
BOUGHT = TRADING / "UI示例，购买了商品.png"
BOTTOM = TRADING / "UI滚到底.png"
FIXTURES = (TOP, BOUGHT, BOTTOM)


class TradeReadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [str(p) for p in FIXTURES if not p.is_file()]
        if missing:
            raise unittest.SkipTest("缺少跑商截图：" + ", ".join(missing))
        if importlib.util.find_spec("paddleocr") is None:
            raise unittest.SkipTest("没装 paddleocr")
        cls.frames = {}
        for path in FIXTURES:
            frame = trade.load_image(path)
            if frame is None:
                raise unittest.SkipTest(f"截图读不出来：{path}")
            cls.frames[path.name] = frame
        cls.top = cls.frames[TOP.name]
        cls.bought = cls.frames[BOUGHT.name]
        cls.bottom = cls.frames[BOTTOM.name]

    # ------------------------------------------------------------ 窗口
    def test_find_shop_window(self):
        for path in FIXTURES:
            with self.subTest(image=path.name):
                self.assertTrue(trade.find_shop_window(self.frames[path.name]))

    def test_find_shop_window_rejects_blank_frame(self):
        import numpy as np

        blank = np.zeros((800, 1368, 3), dtype=np.uint8)
        self.assertFalse(trade.find_shop_window(blank))
        self.assertFalse(trade.find_shop_window(None))

    # ------------------------------------------------------------ 倒计时 / 行
    def test_countdown(self):
        self.assertEqual(trade.read_row_countdown(self.top), "00:00")
        self.assertEqual(trade.read_row_countdown(self.bought), "01:18")
        self.assertEqual(trade.read_row_countdown(self.bottom), "02:11")

    def test_row_count(self):
        # 前两张最后一行只露出十几像素（partial），滚到底那张只有 3 行。
        self.assertEqual(len(trade.read_rows(self.top)), 4)
        self.assertEqual(len(trade.read_rows(self.bought)), 4)
        self.assertEqual(len(trade.read_rows(self.bottom)), 3)

    def test_row_prices_top(self):
        rows = trade.read_rows(self.top)
        self.assertEqual([(r.buy_price, r.sell_price) for r in rows[:3]],
                         [(12, 0), (49, 0), (167, 0)])
        self.assertTrue(rows[3].partial)
        self.assertIsNone(rows[3].buy_price)
        self.assertIsNone(rows[3].sell_price)

    def test_row_prices_bought(self):
        rows = trade.read_rows(self.bought)
        self.assertEqual([(r.buy_price, r.sell_price) for r in rows[:3]],
                         [(13, 0), (45, 0), (0, 22)])
        self.assertFalse(rows[0].partial)
        self.assertTrue(rows[3].partial)

    def test_row_prices_bottom(self):
        rows = trade.read_rows(self.bottom)
        self.assertEqual([(r.buy_price, r.sell_price) for r in rows],
                         [(0, 12), (0, 51), (0, 67)])
        self.assertFalse(any(r.partial for r in rows))

    def test_icon_boxes(self):
        rows = trade.read_rows(self.top)
        self.assertEqual(rows[0].icon_box, (437, 292, 63, 63))
        self.assertEqual(rows[1].icon_box, (437, 379, 63, 63))
        self.assertEqual(rows[2].icon_box, (437, 466, 63, 63))
        # partial 行仍返回完整逻辑槽位，方便下一阶段按槽位裁图。
        self.assertEqual(rows[3].icon_box, (437, 553, 63, 63))

    # ------------------------------------------------------------ CARGO / 滚动条
    def test_cargo(self):
        self.assertEqual(trade.read_cargo(self.top), trade.Cargo(50, 0, 135))
        self.assertEqual(trade.read_cargo(self.bought), trade.Cargo(11, 3, 135))
        self.assertEqual(trade.read_cargo(self.bottom), trade.Cargo(11, 3, 135))

    def test_scroll_handle(self):
        self.assertLess(trade.scroll_handle(self.top), 0.05)
        self.assertLess(trade.scroll_handle(self.bought), 0.05)
        self.assertGreater(trade.scroll_handle(self.bottom), 0.95)
        self.assertIsNone(trade.scroll_handle(None))

    # ------------------------------------------------------------ CLI
    def test_cli_prints_json(self):
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        proc = subprocess.run(
            [sys.executable, "-m", "maplebot.trade", str(BOTTOM)],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["shop"])
        self.assertEqual(payload["countdown"], "02:11")
        self.assertGreaterEqual(payload["scroll"], 0.95)
        self.assertEqual(len(payload["rows"]), 3)
        self.assertEqual(payload["cargo"], {"coins": 11, "weight": 3, "capacity": 135})


if __name__ == "__main__":
    unittest.main()
