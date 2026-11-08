"""maplebot.utils 的单元测试（模板匹配 / 坐标换算 / 颜色过滤）。

全部用合成画面，不需要游戏窗口。
"""

import unittest

import numpy as np

from maplebot import config, utils
from tests.helpers import asset, build_frame


class FakeCapture:
    """只提供 utils 需要的 minimap_ratio。"""

    def __init__(self, ratio):
        self.minimap_ratio = ratio


class MatchTest(unittest.TestCase):
    def setUp(self):
        self.player = asset("player_template.png")

    def test_single_match_finds_exact_patch(self):
        pos = (40, 60)
        frame = build_frame(templates=[(self.player, pos)])
        top_left, bottom_right = utils.single_match(frame, self.player)
        self.assertAlmostEqual(top_left[0], pos[1], delta=1)
        self.assertAlmostEqual(top_left[1], pos[0], delta=1)
        # bottom_right = top_left + (w, h)
        self.assertEqual(
            bottom_right,
            (top_left[0] + self.player.shape[1], top_left[1] + self.player.shape[0]),
        )

    def test_multi_match_returns_center_of_patch(self):
        pos = (40, 60)
        frame = build_frame(templates=[(self.player, pos)])
        results = utils.multi_match(frame, self.player, threshold=0.95)
        self.assertGreaterEqual(len(results), 1)
        h, w = self.player.shape
        expected = (pos[1] + w / 2, pos[0] + h / 2)
        nearest = min(results, key=lambda p: (p[0] - expected[0]) ** 2 + (p[1] - expected[1]) ** 2)
        self.assertLessEqual(abs(nearest[0] - expected[0]), 2)
        self.assertLessEqual(abs(nearest[1] - expected[1]), 2)

    def test_multi_match_threshold_filters_everything(self):
        # 阈值 1.0 时，随机画面里不应有 1.0 的完全匹配（贴图位置在随机噪声下也可能略低于 1）
        frame = build_frame(seed=7)
        results = utils.multi_match(frame, self.player, threshold=1.0)
        self.assertEqual(results, [])

    def test_multi_match_rejects_template_larger_than_frame(self):
        frame = np.zeros((20, 20, 3), np.uint8)
        big = np.zeros((30, 30), np.uint8)
        self.assertEqual(utils.multi_match(frame, big), [])

    def test_single_match_on_uniform_frame_does_not_crash(self):
        # TM_CCOEFF 在纯色画面上会算出 NaN/inf，函数本身不应该抛异常
        frame = np.zeros((100, 100, 3), np.uint8)
        top_left, bottom_right = utils.single_match(frame, self.player)
        self.assertEqual(len(top_left), 2)
        self.assertEqual(len(bottom_right), 2)


class CoordinateTest(unittest.TestCase):
    def setUp(self):
        self._saved = config.capture
        config.capture = FakeCapture(2.0)
        self.frame = np.zeros((100, 200, 3), np.uint8)  # h=100, w=200

    def tearDown(self):
        config.capture = self._saved

    def test_convert_to_relative_uses_ratio_for_vertical_axis(self):
        x, y = utils.convert_to_relative((10, 20), self.frame)
        self.assertAlmostEqual(x, 10 / 200)
        self.assertAlmostEqual(y, 20 / 2.0 / 100)

    def test_convert_to_absolute_inverts_relative(self):
        point = utils.convert_to_relative((10, 20), self.frame)
        self.assertEqual(utils.convert_to_absolute(point, self.frame), (10, 20))

    def test_ratio_defaults_to_one_without_capture(self):
        config.capture = None
        x, y = utils.convert_to_relative((10, 20), self.frame)
        self.assertAlmostEqual(x, 10 / 200)
        self.assertAlmostEqual(y, 20 / 100)

    def test_distance(self):
        self.assertEqual(utils.distance((0, 0), (3, 4)), 5.0)
        self.assertEqual(utils.distance((1, 1), (1, 1)), 0.0)


class FilterColorTest(unittest.TestCase):
    RED_RANGES = (((0, 200, 200), (10, 255, 255)),)
    GREEN_RANGES = (((50, 200, 200), (70, 255, 255)),)

    def _image(self):
        img = np.zeros((2, 2, 3), np.uint8)
        img[0, 0] = (0, 0, 255)    # 纯红 BGR
        img[0, 1] = (0, 255, 0)    # 纯绿 BGR
        return img

    def test_keeps_only_matching_pixels(self):
        filtered = utils.filter_color(self._image(), self.RED_RANGES)
        self.assertEqual(filtered[0, 0].tolist(), [0, 0, 255])
        self.assertEqual(filtered[0, 1].tolist(), [0, 0, 0])
        self.assertEqual(filtered[1, 1].tolist(), [0, 0, 0])

    def test_multiple_ranges_are_or_ed(self):
        filtered = utils.filter_color(self._image(), self.RED_RANGES + self.GREEN_RANGES)
        self.assertEqual(filtered[0, 0].tolist(), [0, 0, 255])
        self.assertEqual(filtered[0, 1].tolist(), [0, 255, 0])

    def test_output_shape_and_dtype(self):
        img = self._image()
        filtered = utils.filter_color(img, self.RED_RANGES)
        self.assertEqual(filtered.shape, img.shape)
        self.assertEqual(filtered.dtype, np.uint8)


if __name__ == "__main__":
    unittest.main()
