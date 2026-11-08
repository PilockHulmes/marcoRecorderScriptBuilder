"""maplebot.minimap 的单元测试：白框定位。

用合成画面（深色背景 + 浅灰白圆角框）+ 可选的真实截图（根目录 rune_example.png）。
"""

import unittest

import cv2
import numpy as np

from maplebot import minimap
from tests.helpers import ROOT

REAL_IMAGE = ROOT / "rune_example.png"

BG = (40, 30, 25)          # 深色底（深蓝黑）
BORDER = (228, 228, 228)   # 实测白框颜色
FRAME = (800, 1368)        # (h, w)


def make_frame(box=(20, 30, 200, 80), thickness=2, sides=("top", "bottom", "left", "right")):
    """造一张带白框的深色画面。SIDES 可以只画其中几条边，用来测试边框残缺。"""
    frame = np.full((FRAME[0], FRAME[1], 3), BG, np.uint8)
    x, y, w, h = box
    if "top" in sides:
        cv2.rectangle(frame, (x, y), (x + w, y + thickness - 1), BORDER, -1)
    if "bottom" in sides:
        cv2.rectangle(frame, (x, y + h - thickness + 1), (x + w, y + h), BORDER, -1)
    if "left" in sides:
        cv2.rectangle(frame, (x, y), (x + thickness - 1, y + h), BORDER, -1)
    if "right" in sides:
        cv2.rectangle(frame, (x + w - thickness + 1, y), (x + w, y + h), BORDER, -1)
    return frame


class FindMinimapTest(unittest.TestCase):
    def test_finds_synthetic_border(self):
        box = minimap.find_minimap(make_frame((20, 30, 200, 80)))
        self.assertIsNotNone(box)
        self.assertLessEqual(abs(box.x - 20), 2, box)
        self.assertLessEqual(abs(box.y - 30), 2, box)
        self.assertLessEqual(abs(box.w - 201), 3, box)
        self.assertLessEqual(abs(box.h - 81), 3, box)

    def test_no_border_returns_none(self):
        frame = np.full((FRAME[0], FRAME[1], 3), BG, np.uint8)
        self.assertIsNone(minimap.find_minimap(frame))

    def test_solid_white_block_is_rejected(self):
        frame = np.full((FRAME[0], FRAME[1], 3), BG, np.uint8)
        cv2.rectangle(frame, (20, 30), (220, 110), BORDER, -1)
        self.assertIsNone(minimap.find_minimap(frame))

    def test_broken_border_is_rejected(self):
        frame = make_frame((20, 30, 200, 80), sides=("top", "left", "right"))
        self.assertIsNone(minimap.find_minimap(frame))

    def test_too_small_is_rejected(self):
        self.assertIsNone(minimap.find_minimap(make_frame((20, 30, 30, 20))))

    def test_too_wide_is_rejected(self):
        self.assertIsNone(minimap.find_minimap(make_frame((10, 30, 600, 100))))

    def test_ring_outside_roi_is_ignored(self):
        self.assertIsNone(minimap.find_minimap(make_frame((600, 30, 200, 80))))

    def test_custom_roi(self):
        frame = make_frame((600, 30, 200, 80))
        box = minimap.find_minimap(frame, roi=(560, 0, 300, 200))
        self.assertIsNotNone(box)
        self.assertLessEqual(abs(box.x - 600), 2, box)

    def test_picks_the_largest_candidate(self):
        frame = make_frame((20, 30, 200, 80))
        cv2.rectangle(frame, (20, 140), (120, 200), BORDER, 2)
        box = minimap.find_minimap(frame)
        self.assertIsNotNone(box)
        self.assertGreater(box.w, 150)

    def test_empty_or_missing_frame(self):
        self.assertIsNone(minimap.find_minimap(None))
        self.assertIsNone(minimap.find_minimap(np.zeros((0, 0, 3), np.uint8)))

    def test_debug_info(self):
        box, info = minimap.find_minimap(make_frame(), debug=True)
        self.assertIsNotNone(box)
        self.assertEqual(len(info["sides"]), 4)
        self.assertGreaterEqual(min(info["sides"]), minimap.SIDE_MIN)
        self.assertIn("threshold", info)
        self.assertGreater(info["border_v"], info["outer_v"])

    def test_scale_invariance(self):
        base = make_frame()
        for scale in (0.75, 1.5):
            frame = cv2.resize(base, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            box = minimap.find_minimap(frame)
            self.assertIsNotNone(box, f"scale={scale}")
            self.assertLessEqual(abs(box.x - 20 * scale), 4, f"scale={scale} {box}")

    def test_shift_invariance(self):
        base = make_frame()
        matrix = np.float32([[1, 0, 25], [0, 1, 15]])
        shifted = cv2.warpAffine(base, matrix, (base.shape[1], base.shape[0]))
        box = minimap.find_minimap(shifted)
        self.assertIsNotNone(box)
        self.assertLessEqual(abs(box.x - 45), 3, box)
        self.assertLessEqual(abs(box.y - 45), 3, box)

    def test_minimap_that_is_mostly_white_is_rejected(self):
        # 白底 + 白框（内部也亮）→ 不是地图
        frame = np.full((FRAME[0], FRAME[1], 3), (240, 240, 240), np.uint8)
        cv2.rectangle(frame, (20, 30), (220, 110), BORDER, 2)
        self.assertIsNone(minimap.find_minimap(frame))


class ToleranceTest(unittest.TestCase):
    """现实约束：小地图尺寸不固定、边框半透明且随背景变色。"""

    PANEL_BG = (40, 40, 40)

    def make_panel(self, map_v=60, alpha=0.8, box=(20, 30, 200, 80), thickness=2):
        """深色面板 + 可变亮度的地图内容 + 半透明白框。"""
        frame = np.full((FRAME[0], FRAME[1], 3), self.PANEL_BG, np.uint8)
        x, y, w, h = box
        frame[y + thickness:y + h - thickness + 1,
              x + thickness:x + w - thickness + 1] = map_v
        # 地图里有地形纹理（纯色地图会和"纯白色块"混淆，这里故意加点细节）
        for offset in range(10, w - 10, 40):
            cv2.line(frame, (x + offset, y + thickness + 2),
                     (x + offset, y + h - thickness - 2), (map_v // 2, map_v // 2, map_v // 2), 1)
        border = tuple(int(alpha * 255 + (1 - alpha) * c) for c in self.PANEL_BG)
        cv2.rectangle(frame, (x, y), (x + w, y + h), border, thickness)
        return frame, border

    def assert_box(self, box, expected, scale=1.0):
        self.assertIsNotNone(box)
        for got, want in zip(box.as_tuple(), expected):
            self.assertLessEqual(abs(got - want * scale), 4, f"{box} vs {expected}")

    def test_border_transparency_ladder(self):
        for alpha in (0.4, 0.6, 0.8, 1.0):
            frame, border = self.make_panel(alpha=alpha)
            with self.subTest(alpha=alpha, border=border):
                self.assert_box(minimap.find_minimap(frame), (20, 30, 201, 81))

    def test_map_brightness_variants(self):
        # 地图内部可能是很暗也可能很亮；判据是"边框比外侧环亮"，不是"内部暗"
        for map_v in (30, 60, 120, 180, 220):
            frame, _ = self.make_panel(map_v=map_v)
            with self.subTest(map_v=map_v):
                self.assert_box(minimap.find_minimap(frame), (20, 30, 201, 81))

    def test_size_and_shape_variants(self):
        for box in ((20, 30, 200, 80), (20, 30, 120, 120), (20, 30, 400, 90),
                    (20, 30, 140, 55), (20, 30, 300, 200)):
            frame, _ = self.make_panel(box=box)
            with self.subTest(size=box[2:]):
                self.assert_box(minimap.find_minimap(frame), box)

    def test_transparency_beats_fixed_white_threshold(self):
        """半透明边框的亮度会低于"纯白"，必须仍然找到。"""
        frame, border = self.make_panel(alpha=0.4)
        self.assertLess(border[0], minimap.THRESHOLDS[0][0])  # 比最严的阈值还暗
        self.assertIsNotNone(minimap.find_minimap(frame))


class BoxTest(unittest.TestCase):
    def test_geometry(self):
        box = minimap.MinimapBox(10, 20, 200, 80)
        self.assertEqual(box.right, 210)
        self.assertEqual(box.bottom, 100)
        self.assertEqual(box.center, (110, 60))
        self.assertEqual(box.as_tuple(), (10, 20, 200, 80))
        self.assertTrue(box.contains(10, 20))
        self.assertTrue(box.contains(209, 99))
        self.assertFalse(box.contains(210, 60))
        self.assertFalse(box.contains(110, 100))

    def test_inner_inset(self):
        box = minimap.MinimapBox(10, 20, 200, 80)
        inner = box.inner(3)
        self.assertEqual(inner.as_tuple(), (13, 23, 194, 74))
        self.assertEqual(box.inner(0).as_tuple(), (10, 20, 200, 80))

    def test_inner_never_collapses(self):
        inner = minimap.MinimapBox(0, 0, 4, 4).inner(10)
        self.assertGreaterEqual(inner.w, 1)
        self.assertGreaterEqual(inner.h, 1)


@unittest.skipUnless(REAL_IMAGE.is_file(), "根目录没有 rune_example.png，跳过真实截图用例")
class RealScreenshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = cv2.imread(str(REAL_IMAGE))

    def test_locates_the_white_panel(self):
        box = minimap.find_minimap(self.frame)
        self.assertIsNotNone(box)
        # 实测 (8, 99, 198, 82)
        self.assertLessEqual(abs(box.x - 8), 6, box)
        self.assertLessEqual(abs(box.y - 99), 6, box)
        self.assertLessEqual(abs(box.w - 198), 8, box)
        self.assertLessEqual(abs(box.h - 82), 8, box)

    def test_player_marker_is_inside_the_inner_area(self):
        box = minimap.find_minimap(self.frame)
        inner = box.inner()
        # 玩家图标（player_template 命中）绝对坐标约 (96, 136)
        self.assertTrue(inner.contains(96, 136), inner)

    def test_scaled_screenshot(self):
        for scale in (0.75, 1.5):
            frame = cv2.resize(self.frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            box = minimap.find_minimap(frame)
            self.assertIsNotNone(box, f"scale={scale}")
            self.assertLessEqual(abs(box.h - 82 * scale), 10, f"scale={scale} {box}")


if __name__ == "__main__":
    unittest.main()
