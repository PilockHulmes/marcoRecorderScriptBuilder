"""maplebot.stop 的单元测试：急停信号、按键记账、收尾松键、补丁可还原。

全程用一个假的 pydirectinput 模块，绝不注入真实按键。
"""

import sys
import threading
import time
import types
import unittest

from maplebot import stop

API = (
    "keyDown", "keyUp", "press", "write", "click", "doubleClick", "tripleClick",
    "mouseDown", "mouseUp", "moveTo", "moveRel", "move", "scroll", "hscroll", "vscroll",
)


class StopTest(unittest.TestCase):
    def setUp(self):
        stop.uninstall()  # 清掉上一个用例可能留下的状态
        self.calls = []
        self.fake = types.ModuleType("pydirectinput")
        for name in API:
            setattr(self.fake, name, self._recorder(name))
        self._saved_module = sys.modules.get("pydirectinput")
        sys.modules["pydirectinput"] = self.fake
        self.originals = {name: getattr(self.fake, name) for name in API}
        self._real_sleep = time.sleep

    def tearDown(self):
        stop.uninstall()
        if self._saved_module is None:
            sys.modules.pop("pydirectinput", None)
        else:
            sys.modules["pydirectinput"] = self._saved_module

    def _recorder(self, name):
        def record(*args, **kwargs):
            self.calls.append((name,) + tuple(str(a) for a in args))
        return record

    # ---------------------------------------------------------------- 补丁
    def test_install_patches_sleep_and_restores_it(self):
        self.assertIs(time.sleep, self._real_sleep)
        stop.install(enabled=False)
        self.assertIsNot(time.sleep, self._real_sleep)
        stop.uninstall()
        self.assertIs(time.sleep, self._real_sleep)

    def test_install_patches_pydirectinput_and_restores(self):
        original = self.fake.keyDown
        stop.install(enabled=False)
        self.assertIsNot(self.fake.keyDown, original)
        stop.uninstall()
        self.assertIs(self.fake.keyDown, original)

    def test_double_install_does_not_stack_wrappers(self):
        stop.install(enabled=False)
        count = len(stop._patched)
        stop.install(enabled=False)
        self.assertEqual(len(stop._patched), count)
        # 包装一次就够了：二次 install 后 __wrapped__ 仍指向原始函数，而不是另一层包装
        self.assertIs(self.fake.keyDown.__wrapped__, self.originals["keyDown"])

    # ---------------------------------------------------------------- 停止信号
    def test_stop_script_is_not_an_exception(self):
        # 必须继承 BaseException，否则脚本里的 except Exception 会把它吞掉
        self.assertTrue(issubclass(stop.StopScript, BaseException))
        self.assertFalse(issubclass(stop.StopScript, Exception))

    def test_check_raises_with_reason(self):
        stop.request_stop("because")
        with self.assertRaises(stop.StopScript) as ctx:
            stop.check()
        self.assertIn("because", str(ctx.exception))

    def test_request_stop_is_idempotent(self):
        stop.request_stop("first")
        stop.request_stop("second")
        self.assertEqual(stop.reason(), "first")

    def test_uninstall_clears_flag_but_keeps_reason(self):
        stop.install(enabled=False)
        stop.request_stop("why")
        stop.uninstall()
        self.assertFalse(stop.is_stopped())
        self.assertEqual(stop.reason(), "why")

    # ---------------------------------------------------------------- 按键记账
    def test_pressed_key_is_released_on_uninstall(self):
        stop.install(enabled=False)
        self.fake.keyDown("f")
        self.assertNotIn(("keyUp", "f"), self.calls)
        stop.uninstall()
        self.assertIn(("keyUp", "f"), self.calls)

    def test_released_key_is_not_released_twice(self):
        stop.install(enabled=False)
        self.fake.keyDown("f")
        self.fake.keyUp("f")
        self.calls.clear()
        stop.uninstall()
        self.assertEqual(self.calls, [])

    def test_mouse_button_is_tracked_and_released(self):
        stop.install(enabled=False)
        self.fake.mouseDown("right")
        stop.uninstall()
        self.assertIn(("mouseUp", "right"), self.calls)

    def test_press_and_write_do_not_track_keys(self):
        stop.install(enabled=False)
        self.fake.press("g")
        self.fake.write("abc")
        self.calls.clear()
        stop.uninstall()
        self.assertEqual(self.calls, [])

    # ---------------------------------------------------------------- 会话
    def test_session_restores_even_on_exception(self):
        with self.assertRaises(RuntimeError):
            with stop.session(enabled=False):
                raise RuntimeError("boom")
        self.assertIs(time.sleep, self._real_sleep)

    def test_session_releases_keys_on_normal_exit(self):
        with stop.session(enabled=False):
            self.fake.keyDown("left")
        self.assertIn(("keyUp", "left"), self.calls)

    def test_sleep_raises_after_stop_in_main_thread(self):
        with stop.session(enabled=False):
            stop.request_stop("now")
            with self.assertRaises(stop.StopScript):
                time.sleep(0.2)

    def test_sleep_in_worker_thread_is_not_interrupted(self):
        errors = []

        def worker():
            try:
                time.sleep(0.05)
            except BaseException as exc:  # noqa: BLE001 - 测试里就是要抓全部
                errors.append(exc)

        with stop.session(enabled=False):
            stop.request_stop("now")
            thread = threading.Thread(target=worker)
            thread.start()
            thread.join(timeout=5)
        self.assertEqual(errors, [])

    def test_patch_does_not_alter_arguments(self):
        stop.install(enabled=False)
        self.fake.keyDown("f")
        self.fake.moveTo(100, 200)
        self.assertEqual(self.calls[0], ("keyDown", "f"))
        self.assertEqual(self.calls[1], ("moveTo", "100", "200"))


if __name__ == "__main__":
    unittest.main()
