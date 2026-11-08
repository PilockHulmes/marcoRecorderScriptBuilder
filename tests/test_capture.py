"""maplebot.capture 的单元测试：小地图自动标定、检测开关、帧间隔。

做法：造一张带模板的合成画面，替换掉截图器与窗口查找，然后调用 calibrate()。
不需要游戏窗口，也不需要真实屏幕。
"""

import contextlib
import io
import unittest
from unittest import mock

import cv2
import numpy as np

from maplebot import capture as capmod
from maplebot import config
from maplebot import player as player_mod
from tests.helpers import ASSETS, FakeGrabber, asset, build_frame, temp_assets

WINDOW_RECT = (100, 50, 900, 650)  # left, top, right, bottom → 800x600
WINDOW_W = WINDOW_RECT[2] - WINDOW_RECT[0]
WINDOW_H = WINDOW_RECT[3] - WINDOW_RECT[1]

REQUIRED_ONLY = ["minimap_tl_template.png", "minimap_br_template.png", "player_template.png"]


def make_capture(**kwargs):
    """用仓库里的真实素材建一个 Capture（不启动线程）。"""
    kwargs.setdefault("assets_dir", str(ASSETS))
    return capmod.Capture("TestWindow", **kwargs)


class CalibrationTest(unittest.TestCase):
    def setUp(self):
        self._saved_capture = config.capture
        self.tl = asset("minimap_tl_template.png")
        self.br = asset("minimap_br_template.png")
        self.player = asset("player_template.png")
        self.tl_pos = (60, 80)     # (y, x)
        self.br_pos = (300, 400)
        self.frame = build_frame(
            width=WINDOW_W,
            height=WINDOW_H,
            templates=[(self.tl, self.tl_pos), (self.br, self.br_pos)],
        )

    def tearDown(self):
        config.capture = self._saved_capture

    def _calibrated(self, frame=None):
        cap = make_capture()
        cap.screenshoter = FakeGrabber(self.frame if frame is None else frame)
        with mock.patch.object(capmod.win32, "find_window", return_value=1), \
                mock.patch.object(capmod.win32, "window_rect", return_value=WINDOW_RECT):
            ok = cap.calibrate()
        return cap, ok

    def test_calibrate_computes_minimap_rect_and_ratio(self):
        cap, ok = self._calibrated()
        self.assertTrue(ok)
        self.assertTrue(cap.calibrated)
        self.assertEqual(cap.minimap_source, "template")  # 合成图没有白框 → 走旧模板
        self.assertEqual(cap.window, {"left": 100, "top": 50, "width": WINDOW_W, "height": WINDOW_H})

        tl_x = self.tl_pos[1] + capmod.MINIMAP_BOTTOM_BORDER
        tl_y = self.tl_pos[0] + capmod.MINIMAP_TOP_BORDER
        self.assertEqual(cap.minimap_topleft_position, (tl_x, tl_y))

        # calibrate 取的是「右下角模板的右下角」，所以要先加上模板自身宽高
        br_corner_x = self.br_pos[1] + self.br.shape[1]
        br_corner_y = self.br_pos[0] + self.br.shape[0]
        br_x = max(tl_x + self.player.shape[1], br_corner_x - capmod.MINIMAP_BOTTOM_BORDER)
        br_y = max(tl_y + self.player.shape[0], br_corner_y - capmod.MINIMAP_BOTTOM_BORDER)
        self.assertEqual(cap.minimap_bottomright_position, (br_x, br_y))
        self.assertAlmostEqual(cap.minimap_ratio, (br_x - tl_x) / (br_y - tl_y))

    def test_calibrate_is_idempotent(self):
        cap, ok = self._calibrated()
        self.assertTrue(ok)
        first = (cap.minimap_topleft_position, cap.minimap_bottomright_position, cap.minimap_ratio)
        with mock.patch.object(capmod.win32, "find_window", return_value=1), \
                mock.patch.object(capmod.win32, "window_rect", return_value=WINDOW_RECT):
            cap.calibrate()
        second = (cap.minimap_topleft_position, cap.minimap_bottomright_position, cap.minimap_ratio)
        self.assertEqual(first, second)

    def test_missing_window_returns_false_and_keeps_uncalibrated(self):
        cap = make_capture()
        cap.screenshoter = FakeGrabber(self.frame)
        with mock.patch.object(capmod.win32, "find_window", return_value=0):
            self.assertFalse(cap.calibrate())
        self.assertFalse(cap.calibrated)

    def test_failed_rect_returns_false(self):
        cap = make_capture()
        cap.screenshoter = FakeGrabber(self.frame)
        with mock.patch.object(capmod.win32, "find_window", return_value=1), \
                mock.patch.object(capmod.win32, "window_rect", return_value=None):
            self.assertFalse(cap.calibrate())
        self.assertFalse(cap.calibrated)

    def test_none_frame_returns_false(self):
        cap = make_capture()
        with mock.patch.object(capmod.win32, "find_window", return_value=1), \
                mock.patch.object(capmod.win32, "window_rect", return_value=WINDOW_RECT), \
                mock.patch.object(capmod.Capture, "screenshot", return_value=None):
            self.assertFalse(cap.calibrate())
        self.assertFalse(cap.calibrated)

    def test_bot_testing_detection_locates_templates(self):
        tl = asset("haiku_bot_testing_tl_template.jpg")
        br = asset("haiku_bot_testing_br_template.jpg")
        pos_tl, pos_br = (200, 500), (260, 620)
        frame = build_frame(width=WINDOW_W, height=WINDOW_H, templates=[(tl, pos_tl), (br, pos_br)])
        cap, ok = self._calibrated(frame=frame)
        self.assertTrue(ok)
        cap.detect_bot_testing = True
        cap.botTestingDetection()
        # botTestingDetection 同样取「左上模板的左上 + 右下模板的右下」
        self.assertEqual(cap.haiku_bot_testing_topleft_position, (pos_tl[1], pos_tl[0]))
        self.assertEqual(
            cap.haiku_bot_testing_bottomright_position,
            (pos_br[1] + br.shape[1], pos_br[0] + br.shape[0]),
        )


class WhiteBorderTest(unittest.TestCase):
    """新版客户端：小地图靠白色圆角边框定位。"""

    def setUp(self):
        self._saved_capture = config.capture
        self.frame = np.full((600, 800, 3), (40, 30, 25), np.uint8)
        cv2.rectangle(self.frame, (20, 30), (220, 110), (228, 228, 228), 2)

    def tearDown(self):
        config.capture = self._saved_capture

    def _calibrate(self, **kwargs):
        cap = make_capture(**kwargs)
        cap.screenshoter = FakeGrabber(self.frame)
        with mock.patch.object(capmod.win32, "find_window", return_value=1), \
                mock.patch.object(capmod.win32, "window_rect", return_value=(0, 0, 800, 600)):
            ok = cap.calibrate()
        return cap, ok

    def test_calibrate_prefers_white_border(self):
        cap, ok = self._calibrate()
        self.assertTrue(ok)
        self.assertEqual(cap.minimap_source, "white_border")
        inner = capmod.minimap_mod.find_minimap(self.frame).inner()
        self.assertEqual(cap.minimap_topleft_position, (inner.x, inner.y))
        self.assertEqual(cap.minimap_bottomright_position, (inner.right, inner.bottom))
        self.assertAlmostEqual(cap.minimap_ratio, inner.w / inner.h)
        self.assertEqual(cap.minimap_sample.shape[:2], (inner.h, inner.w))

    def test_white_border_mode_does_not_fall_back(self):
        blank = np.zeros((600, 800, 3), np.uint8)
        cap = make_capture(minimap_locator="white_border")
        cap.screenshoter = FakeGrabber(blank)
        with mock.patch.object(capmod.win32, "find_window", return_value=1), \
                mock.patch.object(capmod.win32, "window_rect", return_value=(0, 0, 800, 600)):
            self.assertFalse(cap.calibrate())
        self.assertFalse(cap.calibrated)

    def test_template_mode_ignores_white_border(self):
        cap, ok = self._calibrate(minimap_locator="template")
        self.assertTrue(ok)
        self.assertEqual(cap.minimap_source, "template")

    def test_unknown_locator_is_rejected(self):
        with self.assertRaises(ValueError):
            make_capture(minimap_locator="magic")


class FakeClock:
    def __init__(self, now=0.0):
        self.now = float(now)

    def __call__(self):
        return self.now

    def advance(self, dt):
        self.now += float(dt)


class PlayerUpdateTest(unittest.TestCase):
    """Capture._update_player()：把 tracker 的结果写进 config。"""

    def setUp(self):
        self._saved = (config.capture, config.player_position, config.player_stale, config.player_score)
        config.player_position = (0, 0)
        config.player_stale = True
        config.player_score = 0.0

        self.frame = np.full((600, 800, 3), (13, 13, 25), np.uint8)
        cv2.circle(self.frame, (100, 70), 3, (0, 239, 254), -1)   # 黄点
        cv2.circle(self.frame, (100, 70), 4, (255, 255, 255), 1)  # 白圈
        self.blank = np.full((600, 800, 3), (13, 13, 25), np.uint8)

        self.clock = FakeClock()
        self.cap = make_capture()
        self.cap.minimap_content = (30, 40, 180, 60)
        self.cap.player_tracker = player_mod.PlayerTracker(clock=self.clock)

    def tearDown(self):
        config.capture, config.player_position, config.player_stale, config.player_score = self._saved

    def test_writes_normalized_position(self):
        self.cap.frame = self.frame
        self.cap._update_player()
        # 与 utils.convert_to_relative 一致：两个轴都除以内容区宽度
        self.assertAlmostEqual(config.player_position[0], (100 - 30) / 180, places=3)
        self.assertAlmostEqual(config.player_position[1], (70 - 40) / 180, places=3)
        self.assertFalse(config.player_stale)
        self.assertGreater(config.player_score, 0.0)

    def test_lost_tracking_keeps_last_position(self):
        self.cap.frame = self.frame
        self.cap._update_player()
        first = config.player_position
        self.clock.advance(0.2)

        self.cap.frame = self.blank
        self.cap._update_player()
        self.assertEqual(config.player_position, first)     # 保持上一帧
        self.assertFalse(config.player_stale)               # 还在容忍时间内

        self.clock.advance(0.5)
        self.cap._update_player()
        self.assertEqual(config.player_position, first)     # 仍然不归零
        self.assertTrue(config.player_stale)                # 但标记为不可信

    def test_never_located_stays_zero_and_stale(self):
        self.cap.frame = self.blank
        self.cap._update_player()
        self.assertEqual(config.player_position, (0, 0))
        self.assertTrue(config.player_stale)
        self.assertEqual(config.player_score, 0.0)

    def test_missing_minimap_content_marks_stale(self):
        self.cap.frame = self.frame
        self.cap.minimap_content = None
        self.cap._update_player()
        self.assertTrue(config.player_stale)
        self.assertEqual(config.player_position, (0, 0))

    def test_recalibration_resets_tracker(self):
        self.cap.frame = self.frame
        self.cap._update_player()
        self.assertIsNotNone(self.cap.player_tracker.position)
        self.cap.screenshoter = FakeGrabber(self.frame)
        with mock.patch.object(capmod.win32, "find_window", return_value=1), \
                mock.patch.object(capmod.win32, "window_rect", return_value=(0, 0, 800, 600)):
            self.cap.calibrate()
        self.assertIsNone(self.cap.player_tracker.position)


class FlagTest(unittest.TestCase):
    def setUp(self):
        self._saved_capture = config.capture

    def tearDown(self):
        config.capture = self._saved_capture

    def test_all_optional_detections_can_be_off(self):
        cap = make_capture(detect_other=False)
        for flag in ("detect_other", "detect_rune", "detect_blackscreen",
                     "detect_rune_buff", "detect_bot_testing"):
            self.assertFalse(getattr(cap, flag), flag)

    def test_missing_templates_disable_detections_with_warning(self):
        tmp, path = temp_assets(REQUIRED_ONLY)
        self.addCleanup(tmp.cleanup)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cap = capmod.Capture(
                "W",
                assets_dir=str(path),
                detect_rune=True,
                detect_rune_buff=True,
                detect_bot_testing=True,
            )
        for flag in ("detect_rune", "detect_rune_buff", "detect_bot_testing", "detect_other"):
            self.assertFalse(getattr(cap, flag), flag)
        text = out.getvalue()
        for label in ("detect_rune", "detect_rune_buff", "detect_bot_testing", "detect_other"):
            self.assertIn(label, text)

    def test_detect_blackscreen_needs_no_template(self):
        tmp, path = temp_assets(REQUIRED_ONLY)
        self.addCleanup(tmp.cleanup)
        cap = capmod.Capture("W", assets_dir=str(path), detect_blackscreen=True)
        self.assertTrue(cap.detect_blackscreen)

    def test_window_override_wins_over_script_title(self):
        saved = config.window_override
        config.window_override = "Overridden"
        try:
            self.assertEqual(make_capture().window_name, "Overridden")
        finally:
            config.window_override = saved
        self.assertEqual(make_capture().window_name, "TestWindow")

    def test_frame_interval_default_and_setter(self):
        cap = make_capture()
        self.assertEqual(cap.frame_interval, 0.1)
        self.assertEqual(cap.set_frame_interval(0.33), 0.33)
        self.assertEqual(cap.frame_interval, 0.33)
        with self.assertRaises(ValueError):
            cap.set_frame_interval(0)

    def test_missing_assets_dir_raises_readable_error(self):
        with self.assertRaises(FileNotFoundError) as ctx:
            capmod.Capture("W", assets_dir="__definitely_missing__")
        self.assertIn("素材目录不存在", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
