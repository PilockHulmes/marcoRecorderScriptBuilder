"""maplebot.botcheck 的单元测试：面板检测、验证码读取、输入、编排。

真实截图（项目根目录的 detection*.png）是群里其它玩家被监测时的截图：
1/2/4/6 与模板同尺度，3/5/7 尺度不同、只能靠 OCR 兜底。
"""

import unittest

import cv2
import numpy as np

from maplebot import botcheck, rune_api
from tests.helpers import ROOT


def shot(index):
    path = ROOT / f"detection{index}.png"
    return cv2.imread(str(path)) if path.is_file() else None


class FakeVision:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def ask(self, image, system, user, max_tokens=60, detail="high"):
        self.calls += 1
        answer = self.answers[min(self.calls - 1, len(self.answers) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeKeys:
    def __init__(self):
        self.events = []

    def keyDown(self, key):
        self.events.append(("down", key))

    def keyUp(self, key):
        self.events.append(("up", key))

    def typed(self):
        ignore = {"shift", "ctrl", "alt"}
        return "".join(key for event, key in self.events
                       if event == "down" and key not in ignore)


class PanelDetectionTest(unittest.TestCase):
    def test_template_hits_same_scale_screenshots(self):
        for index in (1, 2, 4, 6):
            frame = shot(index)
            if frame is None:
                self.skipTest("缺少 detection 截图")
            panel = botcheck.find_panel(frame)
            self.assertIsNotNone(panel, f"detection{index} 应该命中模板")
            self.assertGreater(panel.score, 0.85)
            x, y, w, h = panel.captcha_bbox
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + w, frame.shape[1])
            self.assertLessEqual(y + h, frame.shape[0])
            # 验证码框在文字块下方
            self.assertGreater(y, panel.text_bbox[1])

    def test_blank_frame_has_no_panel(self):
        self.assertIsNone(botcheck.find_panel(np.zeros((800, 1368, 3), np.uint8)))
        self.assertIsNone(botcheck.find_panel(None))

    def test_template_asset(self):
        self.assertEqual(botcheck.load_panel_template().shape, (64, 156))

    def test_missing_template_raises(self):
        with self.assertRaises(FileNotFoundError):
            botcheck.load_panel_template("__definitely_missing__")

    def test_captcha_crop_and_upscale(self):
        frame = shot(1)
        if frame is None:
            self.skipTest("缺少 detection1.png")
        panel = botcheck.find_panel(frame)
        crop = botcheck.captcha_crop(frame, panel, upscale=2.0)
        _, _, w, h = panel.captcha_bbox
        self.assertEqual((crop.shape[1], crop.shape[0]), (int(w * 2), int(h * 2)))

    @unittest.skipUnless(shot(3) is not None, "缺少 detection3.png")
    def test_ocr_fallback_localises_panel(self):
        frame = shot(3)
        self.assertIsNone(botcheck.find_panel(frame), "这张图模板匹配本来就不该命中")
        panel, source = botcheck.find_panel_any(frame, verify=True)
        self.assertEqual(source, "ocr")
        self.assertIsNotNone(panel)
        x, y, w, h = panel.captcha_bbox
        self.assertGreater(w, 100)          # 放大后的验证码框
        crop = botcheck.captcha_crop(frame, panel, upscale=1.0)
        self.assertEqual(crop.shape[1], w)


class CleanCaptchaTest(unittest.TestCase):
    def test_accepts_plain(self):
        self.assertEqual(botcheck.clean_captcha("QZD"), "QZD")
        self.assertEqual(botcheck.clean_captcha('"igood"'), "igood")
        self.assertEqual(botcheck.clean_captcha(" Q Z D \n"), "QZD")

    def test_rejects_unknown(self):
        self.assertIsNone(botcheck.clean_captcha("UNKNOWN"))
        self.assertIsNone(botcheck.clean_captcha("unknown"))
        self.assertIsNone(botcheck.clean_captcha(""))

    def test_rejects_bad_length_or_chars(self):
        self.assertIsNone(botcheck.clean_captcha("QZ"))
        self.assertIsNone(botcheck.clean_captcha("Q" * 11))
        self.assertIsNone(botcheck.clean_captcha("QZ D!"))
        self.assertIsNone(botcheck.clean_captcha("看不清"))


class ReadCaptchaTest(unittest.TestCase):
    def crop(self):
        return np.zeros((60, 200, 3), np.uint8)

    def test_three_identical_answers(self):
        client = FakeVision(["QZD", "QZD", "QZD"])
        self.assertEqual(botcheck.read_captcha(self.crop(), client=client, attempts=3), "QZD")
        self.assertEqual(client.calls, 3)

    def test_disagreement_returns_none(self):
        client = FakeVision(["QZD", "QZD", "QzD"])
        self.assertIsNone(botcheck.read_captcha(self.crop(), client=client, attempts=3))

    def test_unknown_short_circuits(self):
        client = FakeVision(["UNKNOWN", "QZD", "QZD"])
        self.assertIsNone(botcheck.read_captcha(self.crop(), client=client, attempts=3))
        self.assertEqual(client.calls, 1)

    def test_api_error_returns_none(self):
        client = FakeVision([rune_api.RuneAPIError("网络错误")])
        self.assertIsNone(botcheck.read_captcha(self.crop(), client=client, attempts=3))


class TypeTextTest(unittest.TestCase):
    def test_uppercase_uses_shift_and_ends_with_enter(self):
        keys = FakeKeys()
        botcheck.type_text("aB1", key_api=keys, sleep=lambda _s: None)
        self.assertEqual(
            keys.events,
            [
                ("down", "a"), ("up", "a"),
                ("down", "shift"), ("down", "b"), ("up", "b"), ("up", "shift"),
                ("down", "1"), ("up", "1"),
                ("down", "enter"), ("up", "enter"),
            ],
        )


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.panel_frame = shot(1)
        if self.panel_frame is None:
            self.skipTest("缺少 detection1.png")
        self.blank = np.zeros_like(self.panel_frame)

    def make(self, frames, captcha="QZD", evidence=None, verify_timeout=0.0):
        self.order = []
        self.frames = list(frames)
        self.keys = FakeKeys()
        self.clicks = []

        def capture():
            return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]

        def send(png):
            self.order.append(("evidence", len(png)))
            return evidence if evidence is not None else True

        guard = botcheck.BotCheckGuard(
            capture_frame=capture,
            send_evidence=send,
            click=lambda x, y: (self.clicks.append((x, y)), self.order.append(("click", x, y))),
            key_api=self.keys,
            vision_client=FakeVision([captcha] * 3),
            attempts=3,
            verify_timeout=verify_timeout,
            sleep=lambda _s: None,
        )
        return guard

    def test_no_panel(self):
        guard = self.make([self.blank])
        result = guard.handle()
        self.assertFalse(result.handled)
        self.assertEqual(result.reason, "no_panel")
        self.assertEqual(self.order, [])

    def test_uncertain_captcha_still_sends_evidence(self):
        guard = self.make([self.panel_frame], captcha="UNKNOWN")
        result = guard.handle()
        self.assertFalse(result.handled)
        self.assertEqual(result.reason, "captcha_uncertain")
        self.assertEqual(result.evidence, "ok")
        self.assertEqual(self.keys.events, [])          # 不输入

    def test_solved_flow_order(self):
        guard = self.make([self.panel_frame, self.blank])
        result = guard.handle()
        self.assertTrue(result.handled)
        self.assertEqual(result.reason, "solved")
        self.assertEqual(result.captcha, "QZD")
        # 先取证，再点击/输入
        self.assertEqual(self.order[0][0], "evidence")
        panel = botcheck.find_panel(self.panel_frame)
        self.assertEqual(self.clicks[0], panel.click_point)
        self.assertEqual(self.keys.typed(), "qzdenter")   # 大写用 shift + 小写字母

    def test_click_point_is_the_hint_line(self):
        panel = botcheck.find_panel(self.panel_frame)
        x, y = panel.click_point
        captcha_x, captcha_y, captcha_w, captcha_h = panel.captcha_bbox
        # 提示文字在验证码框下方、水平方向在框内
        self.assertGreater(y, captcha_y + captcha_h - 10)
        self.assertTrue(captcha_x < x < captcha_x + captcha_w)
        # 缩放变化时点击点跟着缩放
        big = botcheck.BotCheckPanel(panel.text_bbox, panel.captcha_bbox, 1.0, scale=2.0)
        self.assertEqual(big.click_point[1] - panel.text_bbox[1],
                         2 * (panel.click_point[1] - panel.text_bbox[1]))

    def test_still_there_types_only_once(self):
        guard = self.make([self.panel_frame])
        result = guard.handle()
        self.assertFalse(result.handled)
        self.assertEqual(result.reason, "still_there")
        self.assertEqual(self.keys.events.count(("down", "enter")), 1)

    def test_evidence_failure_is_reported(self):
        guard = self.make([self.panel_frame, self.blank], evidence=False)
        result = guard.handle()
        self.assertTrue(result.handled)
        self.assertEqual(result.evidence, "failed")


class ChatSignalTest(unittest.TestCase):
    def test_no_template_returns_none(self):
        self.assertIsNone(botcheck.find_chat_line(np.zeros((600, 800, 3), np.uint8)))

    def test_roi_crop_from_game_frame(self):
        frame = np.zeros((600, 800, 3), np.uint8)
        frame[432:570, 0:360] = 200                 # 左下角亮块 = 聊天区
        original = botcheck._window_rect
        botcheck._window_rect = lambda title: None  # 假装没有独立聊天窗口
        try:
            crop = botcheck.chat_crop(frame)
        finally:
            botcheck._window_rect = original
        self.assertIsNotNone(crop)
        self.assertGreater(crop.shape[0], 100)

    def test_template_match_on_synthetic_chat(self):
        frame = np.zeros((600, 800, 3), np.uint8)
        cv2.putText(frame, "BLOCKED ACTION", (20, 500), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        tpl = cv2.cvtColor(frame[480:520, 10:340], cv2.COLOR_BGR2GRAY)
        original = botcheck._window_rect
        botcheck._window_rect = lambda title: None
        try:
            found = botcheck.find_chat_line(frame, template=tpl)
        finally:
            botcheck._window_rect = original
        self.assertIsNotNone(found)
        self.assertGreaterEqual(found[0], 0.95)


if __name__ == "__main__":
    unittest.main()
