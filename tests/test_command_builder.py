"""haikuScripts/commandBuilderLib.py 的按键序列测试（P0 改了它的 delay 实现）。

做法：在子进程里把假 pydirectinput 装进 sys.modules，再把 delay 换成记录器，
于是每个连招都能被断言成「精确的按键/等待序列」。不注入真实按键。

这组测试的作用是**锁死现有手感**：以后重构（比如 P2 的调度器）如果改变了按键顺序或
间隔，这里会立刻失败。
"""

import unittest

from tests.helpers import HAIKU, fake_pydirectinput_source, run_python

CASES = [
    ("keyboardClick", 'lambda: lib.keyboardClick("f")'),
    ("keyboardClickRapid", 'lambda: lib.keyboardClickRapid("g")'),
    ("keyboardPress", 'lambda: lib.keyboardPress("left", 0.1)'),
    ("keyboardRelease", 'lambda: lib.keyboardRelease("right")'),
    ("jump", "lib.jump"),
    ("cleave", "lib.cleave"),
    ("doubleJump", "lib.doubleJump"),
    ("tribleJump", "lib.tribleJump"),
    ("highJump", "lib.highJump"),
    ("downJump", "lib.downJump"),
    ("groundAttack", "lib.groundAttack"),
    ("jumpAttack", "lib.jumpAttack"),
    ("flashJumpAttack", "lib.flashJumpAttack"),
    ("inputAt", "lib.inputAt"),
    ("totem", "lib.totem"),
    ("buffHs", "lib.buffHs"),
    ("delay", "lambda: lib.delay(0.25)"),
    ("delayRandomly", "lambda: lib.delayRandomly(0.1)"),
]

EXPECTED = {
    # keyboardClick: 按下 → 松开 → 等待 interval（默认 INTERVAL_CLICK=0.015）
    "keyboardClick": "keyDown:f keyUp:f sleep:0.015",
    "keyboardClickRapid": "keyDown:g keyUp:g sleep:0.008",
    "keyboardPress": "keyDown:left sleep:0.1",
    "keyboardRelease": "keyUp:right sleep:0.015",
    "jump": "keyDown:g keyUp:g sleep:0.015",
    "cleave": "keyDown:f keyUp:f sleep:0.015 sleep:0.1",
    "doubleJump": "keyDown:g keyUp:g sleep:0.015 keyDown:g keyUp:g sleep:0.015",
    "tribleJump": (
        "keyDown:g keyUp:g sleep:0.015 keyDown:g keyUp:g sleep:0.015 "
        "keyDown:g keyUp:g sleep:0.015"
    ),
    "highJump": (
        "keyDown:g keyUp:g sleep:0.015 keyDown:up sleep:0.015 "
        "keyDown:g keyUp:g sleep:0.015 keyUp:up sleep:0.015"
    ),
    # downJump 直接调 pydirectinput，没有间隔
    "downJump": "keyDown:down keyDown:g keyUp:g keyUp:down",
    "groundAttack": "keyDown:f keyUp:f sleep:0.015 sleep:0.1 sleep:0.3",
    "jumpAttack": (
        "keyDown:g keyUp:g sleep:0.015 keyDown:f keyUp:f sleep:0.015 sleep:0.1 sleep:0.2"
    ),
    "flashJumpAttack": (
        "keyDown:g keyDown:j keyDown:f keyUp:g keyUp:j keyUp:f sleep:0.2"
    ),
    "inputAt": (
        "keyDown:shift sleep:0.015 keyDown:2 sleep:0.015 keyUp:2 sleep:0.015 "
        "keyUp:shift sleep:0.015"
    ),
    # totem 先等 0.2s（等落地），再按 2，再等 0.6s
    "totem": "sleep:0.2 keyDown:2 keyUp:2 sleep:0.015 sleep:0.6",
    "buffHs": "keyDown:5 keyUp:5 sleep:0.015 sleep:1.0",
    "delay": "sleep:0.25",
}


def build_code():
    body = "\n".join(f'show("{label}", {call})' for label, call in CASES)
    return fake_pydirectinput_source(
        prelude="""
        import commandBuilderLib as lib
        from maplebot import timing

        def _record_sleep(seconds):
            calls.append(("sleep", f"{round(float(seconds), 4)}"))

        timing.sleep_precise = _record_sleep
        """,
        postlude=body + "\n",
    )


class CommandSequenceTest(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        result = run_python(build_code(), cwd=HAIKU)
        cls.stderr = result.stderr
        cls.lines = {}
        for line in result.stdout.splitlines():
            if "|" in line:
                label, _, seq = line.partition("|")
                cls.lines[label.strip()] = seq.strip()
        cls.raw = result.stdout

    def test_subprocess_ran_all_cases(self):
        self.assertEqual(set(self.lines), {label for label, _ in CASES}, self.raw + self.stderr)

    def test_key_sequences(self):
        for label, expected in EXPECTED.items():
            with self.subTest(label=label):
                self.assertEqual(self.lines.get(label), expected)

    def test_delay_randomly_has_jitter_in_range(self):
        # 0.1 + uniform(0, 0.07) → 落在 [0.1, 0.17]
        value = float(self.lines["delayRandomly"].split(":")[1])
        self.assertGreaterEqual(value, 0.1)
        self.assertLessEqual(value, 0.17)

    def test_delay_forwards_to_timing(self):
        self.assertEqual(self.lines["delay"], "sleep:0.25")

    def test_check_writes_expected_chat_message(self):
        """check() 应该先切频道，再输入 @ 和 check，最后回车。"""
        code = fake_pydirectinput_source(
            prelude="""
            import commandBuilderLib as lib
            from maplebot import timing
            timing.sleep_precise = lambda seconds: None
            """,
            postlude="""
            calls.clear()
            lib.check()
            print("check", "|", " ".join(f"{c[0]}:{c[1]}" if len(c) > 1 else c[0] for c in calls))
            """,
        )
        result = run_python(code, cwd=HAIKU)
        self.assertIn("write:check", result.stdout, result.stdout + result.stderr)
        self.assertIn("keyDown:enter", result.stdout)
        self.assertIn("keyDown:shift", result.stdout)


if __name__ == "__main__":
    unittest.main()
