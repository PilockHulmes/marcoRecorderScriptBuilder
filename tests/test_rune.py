"""maplebot.rune 的单元测试：面板定位、裁剪、按键序列。

定位部分用合成画面（4 个橙色方块）+ 可选的真实截图（根目录 rune_example.png）。
按键部分注入假的 pydirectinput，绝不注入真实按键。
"""

import unittest
from unittest import mock

import cv2
import numpy as np

from maplebot import rune
from tests.helpers import ROOT

SKY_BGR = (140, 90, 60)      # 蓝色天空 → HSV 蓝色，应被阈值排除
ARROW_BGR = (0, 165, 255)    # 橙色箭头 → H≈21、S=255、V=255，应被选中

REAL_IMAGE = ROOT / "rune_example.png"


def make_frame(width=1368, height=800, positions=None, extra=()):
    """造一张"蓝色天空 + 若干橙色方块"的画面。POSITIONS 是每个方块的左上角。"""
    frame = np.full((height, width, 3), SKY_BGR, np.uint8)
    positions = positions if positions is not None else [(500, 245), (590, 245), (680, 245), (770, 245)]
    for x, y in list(positions) + list(extra):
        cv2.rectangle(frame, (x, y), (x + 26, y + 30), ARROW_BGR, -1)
    return frame


class FindPanelTest(unittest.TestCase):
    def test_finds_four_arrows_sorted_left_to_right(self):
        panel = rune.find_panel(make_frame())
        self.assertIsNotNone(panel)
        self.assertEqual(len(panel), 4)
        xs = [x for x, _, _, _ in panel.arrows]
        self.assertEqual(xs, sorted(xs))

    def test_bbox_covers_all_arrows(self):
        panel = rune.find_panel(make_frame())
        bx, by, bw, bh = panel.bbox
        for x, y, w, h in panel.arrows:
            self.assertGreaterEqual(x, bx)
            self.assertGreaterEqual(y, by)
            self.assertLessEqual(x + w, bx + bw)
            self.assertLessEqual(y + h, by + bh)

    def test_three_arrows_is_not_a_panel(self):
        frame = make_frame(positions=[(500, 245), (590, 245), (680, 245)])
        self.assertIsNone(rune.find_panel(frame))

    def test_five_arrows_in_one_row_is_rejected(self):
        frame = make_frame(positions=[(500, 245), (590, 245), (680, 245), (770, 245), (860, 245)])
        self.assertIsNone(rune.find_panel(frame))

    def test_picks_the_row_with_four_when_noise_exists_elsewhere(self):
        # 额外放一个偏下的橙色块（模拟面板下方的黄字/怪物），不该干扰
        frame = make_frame(extra=[(600, 330)])
        panel = rune.find_panel(frame)
        self.assertIsNotNone(panel)
        self.assertEqual(len(panel), 4)
        self.assertLess(max(y for _, y, _, _ in panel.arrows), 330)

    def test_no_arrows_returns_none(self):
        frame = np.full((800, 1368, 3), SKY_BGR, np.uint8)
        self.assertIsNone(rune.find_panel(frame))

    def test_arrows_outside_roi_are_ignored(self):
        # 放到 y=600（ROI 之外）应该找不到
        frame = make_frame(positions=[(500, 600), (590, 600), (680, 600), (770, 600)])
        self.assertIsNone(rune.find_panel(frame))

    def test_scale_invariance(self):
        base = make_frame()
        for scale in (0.75, 1.5):
            frame = cv2.resize(base, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
            panel = rune.find_panel(frame)
            self.assertIsNotNone(panel, f"scale={scale}")
            self.assertEqual(len(panel), 4, f"scale={scale}")

    def test_translation_invariance(self):
        base = make_frame()
        matrix = np.float32([[1, 0, 25], [0, 1, -20]])
        shifted = cv2.warpAffine(base, matrix, (base.shape[1], base.shape[0]))
        panel = rune.find_panel(shifted)
        self.assertIsNotNone(panel)
        self.assertEqual(len(panel), 4)

    def test_colored_non_arrow_blobs_are_filtered_by_size(self):
        # 大片橙色（比如特效）面积超上限，不应被当成箭头
        frame = np.full((800, 1368, 3), SKY_BGR, np.uint8)
        cv2.rectangle(frame, (450, 230), (900, 320), ARROW_BGR, -1)
        self.assertIsNone(rune.find_panel(frame))


class CropTest(unittest.TestCase):
    def test_crop_is_padded_and_upscaled(self):
        frame = make_frame()
        panel = rune.find_panel(frame)
        crop = rune.crop_panel(frame, panel, padding=20, upscale=3)
        scale = frame.shape[1] / rune.BASE_WIDTH
        pad = int(round(20 * scale))
        expected_w = (panel.bbox[2] + 2 * pad) * 3
        expected_h = (panel.bbox[3] + 2 * pad) * 3
        self.assertEqual(crop.shape[1], expected_w)
        self.assertEqual(crop.shape[0], expected_h)
        self.assertEqual(crop.dtype, np.uint8)

    def test_crop_contains_every_arrow(self):
        frame = make_frame()
        panel = rune.find_panel(frame)
        crop = rune.crop_panel(frame, panel, padding=20, upscale=1)
        # padding 后裁剪区域应包含所有箭头；用橙色像素占比做间接验证
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = ((hsv[:, :, 0] <= 75) & (hsv[:, :, 1] >= 140) & (hsv[:, :, 2] >= 150))
        self.assertGreater(int(mask.sum()), 4 * 26 * 30 * 0.8)

    def test_crop_clamps_at_frame_edges(self):
        frame = make_frame()
        # find_panel 的 ROI 本身就在画面中间，所以这里直接构造一个贴边的 panel
        panel = rune.RunePanel(bbox=(5, 5, 40, 40))
        crop = rune.crop_panel(frame, panel, padding=20, upscale=1)
        # x0/y0 被夹到 0，x1/y1 = 5+40+20 = 65
        self.assertEqual(crop.shape[:2], (65, 65))

        far = rune.RunePanel(bbox=(frame.shape[1] - 30, frame.shape[0] - 30, 40, 40))
        crop = rune.crop_panel(frame, far, padding=20, upscale=1)
        self.assertLessEqual(crop.shape[1], 50)
        self.assertLessEqual(crop.shape[0], 50)

    def test_empty_crop_raises(self):
        frame = make_frame()
        panel = rune.RunePanel(bbox=(frame.shape[1] + 100, 0, 10, 10))
        with self.assertRaises(ValueError):
            rune.crop_panel(frame, panel)


class FakeKeyApi:
    def __init__(self):
        self.events = []

    def keyDown(self, key):
        self.events.append(("down", key))

    def keyUp(self, key):
        self.events.append(("up", key))


class PressDirectionsTest(unittest.TestCase):
    def test_presses_keys_in_order(self):
        api = FakeKeyApi()
        sleeps = []
        rune.press_directions(["down", "down", "left", "down"], key_api=api, sleep=sleeps.append)
        self.assertEqual(
            api.events,
            [("down", "down"), ("up", "down"), ("down", "down"), ("up", "down"),
             ("down", "left"), ("up", "left"), ("down", "down"), ("up", "down")],
        )
        # 4 次 hold + 3 次间隔，交替出现
        self.assertEqual(len(sleeps), 7)
        self.assertEqual(sleeps[0::2], [rune.HOLD] * 4)

    def test_interval_has_jitter_around_100ms(self):
        api = FakeKeyApi()
        sleeps = []
        rune.press_directions(["up", "up", "up", "up"], key_api=api, sleep=sleeps.append)
        gaps = sleeps[1::2]  # hold, gap, hold, gap ...
        self.assertEqual(len(gaps), 3)
        for gap in gaps:
            self.assertGreaterEqual(gap, rune.INTERVAL - rune.JITTER - 1e-9)
            self.assertLessEqual(gap, rune.INTERVAL + rune.JITTER + 1e-9)

    def test_invalid_direction_is_rejected_before_any_key(self):
        api = FakeKeyApi()
        with self.assertRaises(ValueError):
            rune.press_directions(["down", "diagonal", "left", "up"], key_api=api, sleep=lambda s: None)
        self.assertEqual(api.events, [])

    def test_stop_is_checked_before_each_key(self):
        api = FakeKeyApi()
        with mock.patch("maplebot.stop.check") as check:
            rune.press_directions(["up", "down", "left", "right"], key_api=api, sleep=lambda s: None)
        self.assertEqual(check.call_count, 4)

    def test_stop_interrupts_sequence(self):
        api = FakeKeyApi()
        remaining = {"n": 0}

        def fake_check():
            remaining["n"] += 1
            if remaining["n"] >= 3:  # 第三个键之前停下
                raise RuntimeError("stopped")

        with mock.patch("maplebot.stop.check", side_effect=fake_check):
            with self.assertRaises(RuntimeError):
                rune.press_directions(["up", "down", "left", "right"], key_api=api, sleep=lambda s: None)
        # 只按完了前两个
        self.assertEqual(
            api.events,
            [("down", "up"), ("up", "up"), ("down", "down"), ("up", "down")],
        )


@unittest.skipUnless(REAL_IMAGE.is_file(), "根目录没有 rune_example.png，跳过真实截图用例")
class RealScreenshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = cv2.imread(str(REAL_IMAGE))
        cls.panel = rune.find_panel(cls.frame)

    def test_detects_four_arrows(self):
        self.assertIsNotNone(self.panel)
        self.assertEqual(len(self.panel), 4)

    def test_bbox_matches_measured_layout(self):
        x, y, w, h = self.panel.bbox
        # 实测：x 487..777、y 245..282（允许模板/截图微小差异）
        self.assertLessEqual(abs(x - 487), 10, self.panel.bbox)
        self.assertLessEqual(abs(y - 245), 10, self.panel.bbox)
        self.assertLessEqual(abs((x + w) - 777), 15, self.panel.bbox)
        self.assertLessEqual(abs((y + h) - 282), 15, self.panel.bbox)

    def test_crop_looks_reasonable(self):
        crop = rune.crop_panel(self.frame, self.panel)
        self.assertGreater(crop.shape[1], 800)
        self.assertLess(crop.shape[0], crop.shape[1])


@unittest.skipUnless(REAL_IMAGE.is_file(), "根目录没有 rune_example.png，跳过真实截图用例")
class MainCliTest(unittest.TestCase):
    def _run(self, *args):
        from tests.helpers import run_python_raw

        code = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
from maplebot import rune
raise SystemExit(rune._main({list(map(str, args))!r}))
"""
        return run_python_raw(code, cwd=ROOT)

    def test_no_api_prints_panel_and_crop(self):
        result = self._run(REAL_IMAGE, "--no-api")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("面板 bbox=", result.stdout)
        self.assertIn("裁剪后尺寸=", result.stdout)

    def test_missing_image_returns_2(self):
        result = self._run(ROOT / "__no_such_image__.png", "--no-api")
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
