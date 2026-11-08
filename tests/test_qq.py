"""maplebot.qq 的单元测试（全部用假窗口，绝不碰真实 QQ）。"""

import unittest

from maplebot import qq


class QQSendTest(unittest.TestCase):
    def make(self, rect=(100, 100, 1000, 800), dry_run=True, activate_ok=True):
        self.clicks = []
        self.hotkeys = []
        self.clipboard = []

        sender = qq.QQSender(
            group_title="猫叶物语T",
            dry_run=dry_run,
            find_window=lambda fragment: rect,
            activate=lambda fragment: activate_ok,
            click=lambda x, y: self.clicks.append((x, y)),
            hotkey=lambda keys: self.hotkeys.append(tuple(keys)),
            set_clipboard=lambda png: self.clipboard.append(len(png)),
            sleep=lambda _s: None,
        )
        return sender

    def test_dry_run_pastes_but_never_sends(self):
        sender = self.make(dry_run=True)
        result = sender.send(b"fake-png")
        self.assertTrue(result.sent)
        self.assertEqual(result.reason, "dry_run")
        self.assertIn(("ctrl", "v"), self.hotkeys)
        self.assertNotIn(("enter",), self.hotkeys)      # 关键：测试模式不发送
        self.assertEqual(self.clipboard, [len(b"fake-png")])

    def test_click_lands_in_input_box(self):
        sender = self.make(rect=(100, 100, 1000, 800))
        sender.send(b"x")
        x, y = self.clicks[0]
        self.assertEqual(x, 100 + int(1000 * qq.DEFAULT_INPUT_BOX[0]))
        self.assertEqual(y, 100 + int(800 * qq.DEFAULT_INPUT_BOX[1]))

    def test_real_send_presses_enter(self):
        sender = self.make(dry_run=False)
        result = sender.send(b"x")
        self.assertTrue(result.sent)
        self.assertEqual(result.reason, "sent")
        self.assertIn(("enter",), self.hotkeys)

    def test_window_not_found(self):
        sender = self.make()
        sender._find_window = lambda fragment: None
        result = sender.send(b"x")
        self.assertFalse(result.sent)
        self.assertEqual(result.reason, "window_not_found")
        self.assertEqual(self.hotkeys, [])

    def test_activate_failed(self):
        sender = self.make(activate_ok=False)
        result = sender.send(b"x")
        self.assertFalse(result.sent)
        self.assertEqual(result.reason, "activate_failed")

    def test_clipboard_failure(self):
        sender = self.make()
        sender._set_clipboard = lambda png: (_ for _ in ()).throw(RuntimeError("busy"))
        result = sender.send(b"x")
        self.assertFalse(result.sent)
        self.assertTrue(result.reason.startswith("clipboard_failed"))


    def test_falls_back_to_qq_main_window(self):
        # 新版 QQ 的主窗口标题就是 "QQ"，群名只出现在窗口内部
        calls = []

        def find(name):
            calls.append(name)
            return (10, 20, 1000, 800) if name == "QQ" else None

        sender = qq.QQSender(
            group_title="猫叶物语T", dry_run=True, find_window=find,
            activate=lambda name: True, click=lambda x, y: None,
            hotkey=lambda keys: None, set_clipboard=lambda png: None,
            sleep=lambda _s: None,
        )
        result = sender.send(b"x")
        self.assertTrue(result.sent)
        self.assertEqual(calls[:2], ["猫叶物语T", "QQ"])


class FindChatTitleTest(unittest.TestCase):
    def test_substring_match(self):
        titles = ["微信", "猫叶物语T (1002)", "QQ"]
        self.assertEqual(qq.find_chat_title("猫叶物语T", titles), "猫叶物语T (1002)")

    def test_missing(self):
        self.assertIsNone(qq.find_chat_title("不存在的群", ["QQ", "微信"]))

    def test_empty_titles(self):
        self.assertIsNone(qq.find_chat_title("猫叶物语T", ["", None]))


if __name__ == "__main__":
    unittest.main()
