import json
import unittest
from pathlib import Path

import cv2
import numpy as np

from maplebot import shop

ROOT = Path(__file__).resolve().parents[1]
SHOT = ROOT / "screenshots" / "trading" / "UI示例，购买了商品.png"


def load(path):
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


class CountdownTest(unittest.TestCase):
    def test_mm_ss(self):
        self.assertEqual(shop.countdown_seconds("01:18"), 78)

    def test_seconds_only(self):
        self.assertEqual(shop.countdown_seconds("00:09"), 9)

    def test_garbage(self):
        self.assertEqual(shop.countdown_seconds(""), 0)
        self.assertEqual(shop.countdown_seconds(None), 0)


class IdentifyTest(unittest.TestCase):
    def test_fixed_merchant(self):
        merchant_id, name, kind = shop.identify("豐饒的沙漠-1")
        self.assertEqual(kind, "fixed")
        self.assertEqual(merchant_id, "kobi_1")
        self.assertEqual(name, "石鉄")

    def test_random_merchant_map(self):
        merchant_id, name, kind = shop.identify("貿易地帶岔道")
        self.assertEqual(kind, "random")
        self.assertEqual(merchant_id, "")

    def test_unknown_when_empty(self):
        self.assertEqual(shop.identify("")[2], "unknown")


@unittest.skipUnless(SHOT.exists(), "缺少测试截图")
class ReadVisitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.visit = shop.read_visit(load(SHOT), "豐饒的沙漠-1",
                                    learn_names=False, learn_icons=False)

    def test_merchant_and_cargo(self):
        self.assertEqual(self.visit.merchant, "石鉄")
        self.assertEqual(self.visit.refresh_in, 78)
        self.assertEqual(self.visit.coins, 11)
        self.assertEqual(self.visit.weight, 3)
        self.assertEqual(self.visit.capacity, 135)

    def test_rows(self):
        rows = {(r.good_name, r.side): r.price for r in self.visit.rows}
        self.assertEqual(rows.get(("人蔘", "sell")), 13)
        self.assertEqual(rows.get(("蜂蜜", "sell")), 45)
        self.assertEqual(rows.get(("柔軟的綢緞", "buy")), 22)

    def test_icons_matched_confidently(self):
        self.assertTrue(self.visit.rows)
        self.assertTrue(all(r.icon_score >= 0.9 for r in self.visit.rows))

    def test_to_dict_is_json_ready(self):
        payload = json.loads(json.dumps(self.visit.to_dict(), ensure_ascii=False))
        self.assertEqual(payload["merchant_kind"], "fixed")
        self.assertTrue(payload["rows"])


NOBLE_SHOT = Path(__file__).resolve().parent / "fixtures" / "shop_noble_cloth_1368.png"


@unittest.skipUnless(NOBLE_SHOT.exists(), "缺少貴族的布料测试截图")
class NobleClothTest(unittest.TestCase):
    """图标模板曾经采错 + 名字表只有繁体 → 这件货被整行丢掉（2026-11-17）。"""

    @classmethod
    def setUpClass(cls):
        cls.visit = shop.read_visit(load(NOBLE_SHOT), "")

    def test_three_rows_resolved(self):
        rows = {(r.good_id, r.side): r.price for r in self.visit.rows}
        self.assertEqual(rows.get(("black_crystal_shard", "buy")), 75)
        self.assertEqual(rows.get(("golden_peach", "buy")), 228)
        self.assertEqual(rows.get(("noble_satin", "buy")), 225)

    def test_noble_satin_icon_matches(self):
        row = [r for r in self.visit.rows if r.good_id == "noble_satin"][0]
        self.assertGreater(row.icon_score, 0.9)


if __name__ == "__main__":
    unittest.main()
