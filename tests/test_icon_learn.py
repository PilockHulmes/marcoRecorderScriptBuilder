# -*- coding: utf-8 -*-
"""商品名 / 商品图标在线学习的单元测试。

全部用假帧 + 假视觉函数，不碰真实游戏、不联网、不写真实 ``data/``。
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

from maplebot import icon_learn, shop, trade


def read_icon(path):
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


def write_icon(path, image):
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buffer = cv2.imencode(".png", image)
    assert ok
    buffer.tofile(str(path))


def textured(seed):
    rng = np.random.RandomState(seed)
    return rng.randint(0, 256, (63, 63, 3), dtype=np.uint8)


class GoodNamesFileTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "good_names.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_seed_file_has_task_examples(self):
        names = icon_learn.load_good_names()
        self.assertEqual(names.get("人蔘"), "balloon_flower")
        self.assertEqual(names.get("天然蜂蜜"), "natural_honey")
        self.assertEqual(names.get("柔軟的綢緞"), "soft_silk")
        self.assertGreaterEqual(len(names), 35)

    def test_seed_file_covers_every_good(self):
        names = icon_learn.load_good_names()
        self.assertEqual(set(names.values()), set(shop.load_goods()),
                         "每个 good_id 至少有一个名字，缺图商品遇到时才能自动学会")

    def test_record_is_idempotent(self):
        self.assertTrue(icon_learn.record_good_name("蜂蜜", "natural_honey", self.path))
        self.assertFalse(icon_learn.record_good_name("蜂蜜", "natural_honey", self.path))
        self.assertEqual(icon_learn.load_good_names(self.path),
                         {"蜂蜜": "natural_honey"})

    def test_invalid_names_are_rejected(self):
        self.assertFalse(icon_learn.record_good_name("", "pork", self.path))
        self.assertFalse(icon_learn.record_good_name("Unknown", "pork", self.path))
        self.assertFalse(icon_learn.record_good_name("这是一个非常非常长的商品名字", "pork",
                                                     self.path))
        self.assertEqual(icon_learn.load_good_names(self.path), {})

    def test_clean_vision_text(self):
        self.assertEqual(icon_learn.clean_goods_name("「人蔘」"), "人蔘")
        self.assertEqual(icon_learn.clean_goods_name("商品名：柔軟的綢緞。"), "柔軟的綢緞")
        self.assertEqual(icon_learn.clean_goods_name("蜂蜜（天然）"), "蜂蜜")
        self.assertEqual(icon_learn.clean_goods_name("Unknown"), "")
        self.assertEqual(icon_learn.clean_goods_name(None), "")


class LoadTemplatesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_scan_picks_up_learned_icon_and_skips_non_goods(self):
        write_icon(self.dir / "balloon_flower.png", textured(1))
        write_icon(self.dir / "cargo_header.png", textured(2))
        templates = shop.load_icon_templates(icon_dir=self.dir,
                                             index_path=self.dir / "missing.json")
        self.assertIn("balloon_flower", templates)
        self.assertNotIn("cargo_header", templates)


class ReadVisitLearningTest(unittest.TestCase):
    def setUp(self):
        icon_learn.reset_learning_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.names_path = self.dir / "good_names.json"
        self.icon_dir = self.dir / "icons"
        self.unknown_dir = self.dir / "icons_unknown"
        self.index_path = self.dir / "merchant_index.json"
        self.frame = np.zeros((600, 800, 3), dtype=np.uint8)

    def tearDown(self):
        self._tmp.cleanup()
        icon_learn.reset_learning_cache()

    # ---------------------------------------------------------------- 工具
    def set_names(self, mapping):
        self.names_path.write_text(json.dumps(mapping, ensure_ascii=False),
                                   encoding="utf-8")

    def make_row(self, top, buy=10, sell=0):
        return trade.Row(icon_box=(50, top, 63, 63), name_ocr="",
                         buy_price=buy, sell_price=sell, partial=False)

    def put_patch(self, top, image):
        self.frame[top:top + 63, 50:113] = image

    def read(self, rows, vision, templates=None, **kwargs):
        if templates is None:
            templates = {}
        with mock.patch.object(shop.trade, "read_rows", return_value=rows), \
             mock.patch.object(shop.trade, "read_row_countdown", return_value=""), \
             mock.patch.object(shop.trade, "read_cargo",
                               side_effect=RuntimeError("没有货舱")):
            return shop.read_visit(
                self.frame, "", templates=templates, vision=vision,
                names_path=self.names_path, icon_dir=self.icon_dir,
                unknown_dir=self.unknown_dir, index_path=self.index_path,
                **kwargs,
            )

    # ---------------------------------------------------------------- 用例
    def test_unknown_icon_with_known_name_saves_icon_and_records_row(self):
        self.set_names({"人蔘": "balloon_flower"})
        patch = textured(3)
        self.put_patch(100, patch)

        visit = self.read([self.make_row(100, buy=13)], vision=lambda crop: "人蔘")

        self.assertEqual(len(visit.rows), 1)
        row = visit.rows[0]
        self.assertEqual(row.good_id, "balloon_flower")
        self.assertEqual(row.good_name, "桔梗")
        self.assertEqual(row.side, "sell")
        self.assertEqual(row.price, 13)

        saved = self.icon_dir / "balloon_flower.png"
        self.assertTrue(saved.exists(), "缺图时应当把图标写进临时 icons 目录")
        self.assertTrue(np.array_equal(read_icon(saved), patch))
        self.assertEqual(list(self.unknown_dir.glob("*.png")) if self.unknown_dir.exists()
                         else [], [])

        reloaded = shop.load_icon_templates(icon_dir=self.icon_dir,
                                            index_path=self.index_path)
        self.assertIn("balloon_flower", reloaded, "重新加载模板后应当能认出新图标")

    def test_unknown_icon_with_unknown_name_does_not_break_other_rows(self):
        self.set_names({"人蔘": "balloon_flower"})
        self.put_patch(100, textured(4))
        self.put_patch(200, textured(5))
        names = iter(["人蔘", "神秘貨物"])

        with self.assertLogs("maplebot.shop", level="INFO") as logs:
            visit = self.read([self.make_row(100, buy=13),
                               self.make_row(200, buy=99)],
                              vision=lambda crop: next(names))

        self.assertEqual([(r.good_id, r.price) for r in visit.rows],
                         [("balloon_flower", 13)])
        unknown = list(self.unknown_dir.glob("*.png"))
        self.assertEqual(len(unknown), 1, "认不出名字的图标应当落进 icons_unknown")
        self.assertTrue(np.array_equal(read_icon(unknown[0]), textured(5)))
        self.assertTrue(any("认不出" in line for line in logs.output), logs.output)

    def test_seeded_volatile_name_learns_its_icon(self):
        # 10 个波动货一开始没有图标；只要名字表里有它，遇到一次就能补上
        self.names_path.write_text(
            json.dumps(icon_learn.load_good_names(), ensure_ascii=False),
            encoding="utf-8")
        patch = textured(13)
        self.put_patch(100, patch)

        visit = self.read([self.make_row(100, buy=150)],
                          vision=lambda crop: "提煉的鋰")

        self.assertEqual([(r.good_id, r.price) for r in visit.rows],
                         [("refined_lithium", 150)])
        saved = self.icon_dir / "refined_lithium.png"
        self.assertTrue(saved.exists())
        self.assertTrue(np.array_equal(read_icon(saved), patch))

    def test_existing_icon_is_not_overwritten(self):
        self.set_names({"人蔘": "balloon_flower"})
        original = textured(6)
        saved = self.icon_dir / "balloon_flower.png"
        write_icon(saved, original)
        before = saved.read_bytes()
        self.put_patch(100, textured(7))

        visit = self.read([self.make_row(100, buy=13)], vision=lambda crop: "人蔘")

        self.assertEqual(len(visit.rows), 1)
        self.assertEqual(saved.read_bytes(), before, "已有图标绝不能覆盖")

    def test_vision_exception_is_silent(self):
        self.set_names({"人蔘": "balloon_flower"})
        self.put_patch(100, textured(8))

        def boom(crop):
            raise RuntimeError("网络断了")

        visit = self.read([self.make_row(100, buy=13)], vision=boom)

        self.assertEqual(visit.rows, [])
        self.assertEqual(list(self.icon_dir.glob("*.png")) if self.icon_dir.exists()
                         else [], [])
        self.assertEqual(list(self.unknown_dir.glob("*.png")) if self.unknown_dir.exists()
                         else [], [])
        self.assertEqual(icon_learn.load_good_names(self.names_path),
                         {"人蔘": "balloon_flower"})

    def test_vision_exception_does_not_affect_matched_row(self):
        self.set_names({})
        template = textured(9)
        self.put_patch(100, template)

        visit = self.read([self.make_row(100, buy=13)],
                          vision=lambda crop: (_ for _ in ()).throw(RuntimeError("断网")),
                          templates={"balloon_flower": template})

        self.assertEqual(len(visit.rows), 1)
        self.assertEqual(visit.rows[0].good_id, "balloon_flower")
        self.assertEqual(icon_learn.load_good_names(self.names_path), {})

    def test_matched_icon_learns_name_once(self):
        self.set_names({})
        template = textured(10)
        self.put_patch(100, template)
        vision = mock.MagicMock(return_value="人蔘")
        templates = {"balloon_flower": template}

        visit = self.read([self.make_row(100, buy=13)], vision=vision,
                          templates=templates)
        self.assertEqual(visit.rows[0].good_id, "balloon_flower")
        self.assertEqual(icon_learn.load_good_names(self.names_path),
                         {"人蔘": "balloon_flower"})
        self.assertEqual(vision.call_count, 1)

        # 名字已经记住了，第二次不再请求视觉
        self.read([self.make_row(100, buy=13)], vision=vision, templates=templates)
        self.assertEqual(vision.call_count, 1, "同一个 good_id 不应反复调用视觉")

    def test_icon_learning_switch_off(self):
        self.set_names({"人蔘": "balloon_flower"})
        self.put_patch(100, textured(11))
        vision = mock.MagicMock(return_value="人蔘")

        visit = self.read([self.make_row(100, buy=13)], vision=vision,
                          learn_icons=False)

        self.assertEqual(visit.rows, [])
        self.assertFalse((self.icon_dir / "balloon_flower.png").exists())
        vision.assert_not_called()

    def test_name_learning_switch_off(self):
        self.set_names({})
        template = textured(12)
        self.put_patch(100, template)
        vision = mock.MagicMock(return_value="人蔘")

        visit = self.read([self.make_row(100, buy=13)], vision=vision,
                          templates={"balloon_flower": template},
                          learn_names=False)

        self.assertEqual(visit.rows[0].good_id, "balloon_flower")
        self.assertEqual(icon_learn.load_good_names(self.names_path), {})
        vision.assert_not_called()


if __name__ == "__main__":
    unittest.main()
