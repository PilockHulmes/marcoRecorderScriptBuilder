"""maplebot.win32 的单元测试：用假的 user32 验证窗口查找/矩形/可截屏判断。

不调用真实 Win32 API（只替换模块里的 ``user32`` 引用）。
"""

import unittest
from unittest import mock

from maplebot import win32


class FakeUser32:
    def __init__(self, handles=None, rect=(0, 0, 0, 0), rect_ok=True, is_window=True,
                 visible=True, iconic=False):
        self.handles = handles or {}
        self.rect = rect
        self.rect_ok = rect_ok
        self._is_window = is_window
        self._visible = visible
        self._iconic = iconic
        self.calls = []

    def FindWindowW(self, cls, title):
        self.calls.append(("FindWindowW", title))
        return self.handles.get(title, 0)

    def GetWindowRect(self, handle, ptr):
        self.calls.append(("GetWindowRect", handle))
        if not self.rect_ok:
            return 0
        # 真实调用传进来的是 LP_RECT（ctypes.pointer(rect)），contents 是活视图
        obj = ptr.contents
        obj.left, obj.top, obj.right, obj.bottom = self.rect
        return 1

    def IsWindow(self, handle):
        return int(self._is_window)

    def IsWindowVisible(self, handle):
        return int(self._visible)

    def IsIconic(self, handle):
        return int(self._iconic)


def patch_user32(fake):
    return mock.patch.object(win32, "user32", fake)


class FindWindowTest(unittest.TestCase):
    def test_empty_title_returns_zero_without_calling_api(self):
        fake = FakeUser32(handles={"": 7})
        with patch_user32(fake):
            self.assertEqual(win32.find_window(""), 0)
        self.assertEqual(fake.calls, [])

    def test_returns_handle(self):
        fake = FakeUser32(handles={"MapleStory": 42})
        with patch_user32(fake):
            self.assertEqual(win32.find_window("MapleStory"), 42)
            self.assertEqual(win32.find_window("Nope"), 0)

    def test_exact_title_only(self):
        fake = FakeUser32(handles={"MapleStory": 42})
        with patch_user32(fake):
            self.assertEqual(win32.find_window("maple"), 0)


class WindowRectTest(unittest.TestCase):
    def test_clamps_negative_coordinates(self):
        fake = FakeUser32(rect=(-30, -10, 300, 200))
        with patch_user32(fake):
            self.assertEqual(win32.window_rect(1), (0, 0, 300, 200))

    def test_returns_raw_rect_for_positive_coordinates(self):
        fake = FakeUser32(rect=(100, 50, 400, 250))
        with patch_user32(fake):
            self.assertEqual(win32.window_rect(1), (100, 50, 400, 250))

    def test_returns_none_for_zero_handle(self):
        fake = FakeUser32()
        with patch_user32(fake):
            self.assertIsNone(win32.window_rect(0))
        self.assertEqual(fake.calls, [])

    def test_returns_none_when_api_fails(self):
        fake = FakeUser32(rect_ok=False)
        with patch_user32(fake):
            self.assertIsNone(win32.window_rect(1))


class CapturableTest(unittest.TestCase):
    def test_zero_handle(self):
        self.assertFalse(win32.is_capturable(0))

    def test_normal_window(self):
        with patch_user32(FakeUser32()):
            self.assertTrue(win32.is_capturable(1))

    def test_minimized_window_is_not_capturable(self):
        with patch_user32(FakeUser32(iconic=True)):
            self.assertFalse(win32.is_capturable(1))

    def test_hidden_window_is_not_capturable(self):
        with patch_user32(FakeUser32(visible=False)):
            self.assertFalse(win32.is_capturable(1))

    def test_invalid_window(self):
        with patch_user32(FakeUser32(is_window=False)):
            self.assertFalse(win32.is_capturable(1))

    def test_find_ready_window_combines_both_steps(self):
        with patch_user32(FakeUser32(handles={"G": 5})), \
                mock.patch.object(win32, "is_capturable", return_value=True):
            self.assertEqual(win32.find_ready_window("G"), 5)
        with patch_user32(FakeUser32(handles={"G": 5})), \
                mock.patch.object(win32, "is_capturable", return_value=False):
            self.assertEqual(win32.find_ready_window("G"), 0)


class WaitForWindowTest(unittest.TestCase):
    def test_returns_first_ready_title(self):
        with patch_user32(FakeUser32(handles={"B": 2})), \
                mock.patch.object(win32, "is_capturable", return_value=True):
            self.assertEqual(win32.wait_for_window(["A", "B"], timeout=0), "B")

    def test_timeout_returns_none(self):
        with patch_user32(FakeUser32(handles={})):
            self.assertIsNone(win32.wait_for_window(["A"], timeout=0))

    def test_ignores_empty_titles(self):
        with patch_user32(FakeUser32(handles={})):
            self.assertIsNone(win32.wait_for_window(["", None], timeout=0))

    def test_polls_until_ready(self):
        # 第一次调用还没出现，第二次才出现
        answers = iter([0, 0, 3])
        with mock.patch.object(win32, "find_ready_window", side_effect=lambda t: next(answers)), \
                mock.patch.object(win32.time, "sleep"):
            self.assertEqual(win32.wait_for_window(["G"], timeout=1, poll=0), "G")

    def test_on_wait_callback_is_called(self):
        seen = []
        with patch_user32(FakeUser32(handles={})), \
                mock.patch.object(win32.time, "sleep"):
            win32.wait_for_window(["G"], timeout=0.05, poll=0, on_wait=seen.append)
        self.assertTrue(seen)


if __name__ == "__main__":
    unittest.main()
