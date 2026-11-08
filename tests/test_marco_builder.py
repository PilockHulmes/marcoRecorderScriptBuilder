"""marcoRecorder/commandBuilderLib.py（离线 .mcr 生成器）的单元测试。

这个模块和 haikuScripts 里同名的那个**不是同一份实现**（一个生成文本，一个直接注入按键），
所以按文件路径单独加载，避免 import 冲突。
"""

import importlib.util
import tempfile
import unittest

from tests.helpers import MARCO, run_python_raw


def load_marco_builder():
    spec = importlib.util.spec_from_file_location("marco_cblib", MARCO / "commandBuilderLib.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrimitiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = load_marco_builder()

    def test_key_commands(self):
        self.assertEqual(self.lib.keyDown("F"), "Keyboard : F : KeyDown")
        self.assertEqual(self.lib.keyUp("F"), "Keyboard : F : KeyUp")

    def test_wait(self):
        self.assertEqual(self.lib.wait(70), "DELAY : 70")
        self.assertEqual(self.lib.wait(0), "DELAY : 0")

    def test_join(self):
        self.assertEqual(self.lib.join(["a", "b", "c"]), "a\nb\nc")
        self.assertEqual(self.lib.join([]), "")

    def test_for_loop_wraps_body(self):
        text = self.lib.forLoop(3, "CMD")
        lines = text.splitlines()
        self.assertEqual(lines[0], "REPEAT : 3 : 0 : 0 : Enter the number of iterations: : 0 : 0")
        self.assertEqual(lines[1], "CMD")
        self.assertEqual(lines[2], "ENDREPEAT")

    def test_count_duration_sums_all_delays(self):
        # 注意：正则要求 DELAY 后面跟着换行，所以「最后一行没有换行」的那条不会被计入
        joined = self.lib.join([self.lib.wait(70), "x", self.lib.wait(30), self.lib.wait(5)])
        self.assertEqual(self.lib.countDuration(joined), 100)
        self.assertEqual(self.lib.countDuration(joined + "\n"), 105)

    def test_count_duration_with_no_delay(self):
        self.assertEqual(self.lib.countDuration("Keyboard : F : KeyDown"), 0)
        self.assertEqual(self.lib.countDuration(""), 0)

    def test_click_uses_70ms_interval(self):
        text = self.lib.click("Left")
        self.assertEqual(
            text.splitlines(),
            ["Keyboard : Left : KeyDown", "DELAY : 70", "Keyboard : Left : KeyUp"],
        )

    def test_double_click_repeats_with_interval(self):
        text = self.lib.doubleClick("Left")
        self.assertEqual(text.count("Keyboard : Left : KeyDown"), 2)
        self.assertEqual(text.count("DELAY : 70"), 3)  # 两次 click 间隔 + 两次 click 内部

    def test_holding_wraps_then_commands(self):
        text = self.lib.holding("Left", then=self.lib.wait(10))
        lines = text.splitlines()
        self.assertEqual(lines[0], "Keyboard : Left : KeyDown")
        self.assertEqual(lines[-1], "Keyboard : Left : KeyUp")
        self.assertIn("DELAY : 10", text)

    def test_holding_multiple_nests_keys(self):
        text = self.lib.holdingMultiple(["Left", "Up"], then=self.lib.wait(5))
        self.assertEqual(text.count("Keyboard : Left : KeyDown"), 1)
        self.assertEqual(text.count("Keyboard : Up : KeyDown"), 1)
        self.assertEqual(text.count("Keyboard : Up : KeyUp"), 1)
        self.assertEqual(text.count("Keyboard : Left : KeyUp"), 1)
        # 最后一个按下的是 Up，它必须在 Left 松开之前松开
        self.assertLess(text.index("Keyboard : Up : KeyUp"), text.index("Keyboard : Left : KeyUp"))

    def test_repeat_loop_helper(self):
        inner = self.lib.join([self.lib.keyDown("F"), self.lib.keyUp("F")])
        self.assertEqual(self.lib.forLoop(2, inner).count("ENDREPEAT"), 1)


class ScriptOutputTest(unittest.TestCase):
    def _run_script(self, script, filename):
        with tempfile.TemporaryDirectory() as tmp:
            code = f"""
import os, runpy, sys
sys.path.insert(0, {str(MARCO)!r})
os.chdir({tmp!r})
runpy.run_path(os.path.join({str(MARCO)!r}, {script!r}), run_name="__main__")
print("files", sorted(os.listdir(".")))
text = open({filename!r}, encoding="utf-8").read()
print("has_keyboard", "Keyboard :" in text)
print("has_delay", "DELAY :" in text)
print("lines", len(text.splitlines()))
"""
            return run_python_raw(code, cwd=MARCO), tmp

    def test_script_writer_produces_mcr(self):
        result, _ = self._run_script("scriptWriter.py", "script.mcr")
        self.assertIn("script.mcr", result.stdout, result.stdout + result.stderr)
        self.assertIn("has_keyboard True", result.stdout)
        self.assertIn("has_delay True", result.stdout)

    def test_adele_truth2_produces_nested_mcr(self):
        result, _ = self._run_script("adele-truth2.py", "adele-truth2.mcr")
        self.assertIn("adele-truth2.mcr", result.stdout, result.stdout + result.stderr)
        self.assertIn("has_keyboard True", result.stdout)
        self.assertIn("lines", result.stdout)


if __name__ == "__main__":
    unittest.main()
