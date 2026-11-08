"""maplebot.keys 的单元测试（全部 dry_run，不真的按任何键）。"""

import time
import unittest

from maplebot import keys


class Recorder:
    def __init__(self):
        self.sleeps = []

    def __call__(self, seconds):
        self.sleeps.append(float(seconds))


class KeyboardTest(unittest.TestCase):
    def make(self):
        recorder = Recorder()
        return keys.Keyboard(sleep=recorder, dry_run=True), recorder

    def test_tap_holds_between_down_and_up(self):
        board, recorder = self.make()
        board.tap("a", hold=0.05)
        self.assertEqual([event[1] for event in board.events], ["down", "up"])
        self.assertEqual(recorder.sleeps, [0.05])

    def test_no_hidden_sleep_after_up(self):
        # pydirectinput 每次 keyDown/keyUp 后各睡 100ms；这里必须只有 hold 这一次
        board, recorder = self.make()
        board.tap("g", hold=0.04)
        self.assertEqual(len(recorder.sleeps), 1)

    def test_burst_holds_every_press(self):
        board, recorder = self.make()
        board.burst("g", count=3, hold=0.04, gap=0.06)
        self.assertEqual([event[1] for event in board.events], ["down", "up"] * 3)
        self.assertEqual(recorder.sleeps, [0.04, 0.06, 0.04, 0.06, 0.04])

    def test_hold_passes_duration(self):
        board, recorder = self.make()
        board.tap("right", hold=0.35)
        self.assertEqual(recorder.sleeps, [0.35])

    def test_release_all_sends_up(self):
        board, _ = self.make()
        board.down("left")
        board.down("g")
        board.release_all()
        ups = [event[2] for event in board.events if event[1] == "up"]
        self.assertCountEqual(ups, ["left", "g"])
        self.assertEqual(board.pressed, set())

    def test_click_emits_mouse_events(self):
        board, _ = self.make()
        board.click(100, 200)
        kinds = [event[1] for event in board.events]
        self.assertIn("mouse:2", kinds)
        self.assertIn("mouse:4", kinds)

    def test_unknown_key_raises(self):
        with self.assertRaises(KeyError):
            keys.virtual_key("不存在的键")

    def test_virtual_key_table(self):
        self.assertEqual(keys.virtual_key("a"), ord("A"))
        self.assertEqual(keys.virtual_key("7"), ord("7"))
        self.assertEqual(keys.virtual_key("ENTER"), 0x0D)
        self.assertEqual(keys.virtual_key("f5"), 0x74)


class PreciseTimerTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._orig = (keys.time_begin, keys.time_end)
        keys.time_begin = lambda: self.calls.append("begin")
        keys.time_end = lambda: self.calls.append("end")

    def tearDown(self):
        keys.time_begin, keys.time_end = self._orig
        keys.precise_timer._depth = 0

    def test_begin_and_end_around_block(self):
        with keys.precise_timer():
            self.assertEqual(self.calls, ["begin"])
        self.assertEqual(self.calls, ["begin", "end"])

    def test_end_even_on_exception(self):
        with self.assertRaises(ValueError):
            with keys.precise_timer():
                raise ValueError("boom")
        self.assertEqual(self.calls, ["begin", "end"])

    def test_nested_switches_only_once(self):
        with keys.precise_timer():
            with keys.precise_timer():
                pass
        self.assertEqual(self.calls, ["begin", "end"])


@unittest.skipUnless(hasattr(time, "perf_counter"), "需要 Windows")
class RealtimeTest(unittest.TestCase):
    def test_hold_duration_is_accurate(self):
        # 真实 sleep_precise：50ms 的按住，误差应在 ±10ms 内
        board = keys.Keyboard(dry_run=True)
        start = time.perf_counter()
        board.tap("a", hold=0.05)
        elapsed = time.perf_counter() - start
        self.assertGreaterEqual(elapsed, 0.045)
        self.assertLess(elapsed, 0.08)


if __name__ == "__main__":
    unittest.main()
