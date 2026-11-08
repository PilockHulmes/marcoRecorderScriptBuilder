"""maplebot.runner 的单元测试：脚本查找、分类、import 解析、窗口探测、CLI 分发。

这里只测「不需要游戏」的部分；真正跑脚本的端到端用例在 test_cli.py。
"""

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from maplebot import runner
from tests.helpers import HAIKU, MARCO, ROOT


class ResolveScriptTest(unittest.TestCase):
    def test_resolve_by_name_in_haiku_scripts(self):
        self.assertEqual(runner.resolve_script("s2_clp"), (HAIKU / "s2_clp.py").resolve())

    def test_resolve_by_name_in_marco_recorder(self):
        self.assertEqual(runner.resolve_script("adele-truth1"), (MARCO / "adele-truth1.py").resolve())

    def test_resolve_with_base_dir(self):
        path = runner.resolve_script("loop_forever", base_dir=ROOT / "tests" / "fixtures")
        self.assertEqual(path, (ROOT / "tests" / "fixtures" / "loop_forever.py").resolve())

    def test_resolve_relative_path(self):
        old = os.getcwd()
        os.chdir(ROOT)
        try:
            self.assertEqual(
                runner.resolve_script("haikuScripts/s2_clp.py"),
                (HAIKU / "s2_clp.py").resolve(),
            )
        finally:
            os.chdir(old)

    def test_resolve_absolute_path(self):
        target = HAIKU / "castleGolem.py"
        self.assertEqual(runner.resolve_script(str(target)), target.resolve())

    def test_missing_script_suggests_similar_name(self):
        with self.assertRaises(SystemExit) as ctx:
            runner.resolve_script("s2_clpp")
        self.assertIn("s2_clp", str(ctx.exception))

    def test_missing_file_with_py_suffix(self):
        with self.assertRaises(SystemExit) as ctx:
            runner.resolve_script("nope_not_here.py")
        self.assertIn("文件不存在", str(ctx.exception))


class ClassifyTest(unittest.TestCase):
    def kind(self, rel):
        return runner.classify(ROOT / rel)

    def test_marco_recorder_is_generator(self):
        kind, notes = self.kind("marcoRecorder/adele-truth1.py")
        self.assertEqual(kind, "生成器")
        self.assertIn("输出 .mcr", notes)

    def test_haiku_capture_is_library(self):
        self.assertEqual(self.kind("haikuScripts/capture.py")[0], "库")

    def test_auto_maple_src_is_library(self):
        self.assertEqual(self.kind("auto-maple/src/capture.py")[0], "库")

    def test_auto_maple_main_is_debug(self):
        self.assertEqual(self.kind("auto-maple/main.py")[0], "调试")

    def test_debug_scripts(self):
        for rel in ("haikuScripts/clicker.py", "haikuScripts/fallout4build.py"):
            self.assertEqual(self.kind(rel)[0], "调试", rel)

    def test_route_notes(self):
        kind, notes = self.kind("haikuScripts/s2_clp.py")
        self.assertEqual(kind, "路线")
        self.assertIn("视觉闭环", notes)

    def test_ocr_tool_notes(self):
        kind, notes = self.kind("haikuScripts/cat_wash_cube.py")
        self.assertEqual(kind, "路线")
        self.assertIn("OCR", notes)

    def test_khali_route_notes(self):
        _, notes = self.kind("haikuScripts/khali_library_1.py")
        self.assertIn("khali", notes)


class UsesCaptureTest(unittest.TestCase):
    def test_scripts_that_use_capture(self):
        for name in ("s2_clp", "khali_library_1", "cat_wash_cube", "cat_open_fami"):
            self.assertTrue(runner.uses_capture(HAIKU / f"{name}.py"), name)

    def test_scripts_that_do_not(self):
        for path in (MARCO / "adele-truth1.py", MARCO / "scriptWriter.py", HAIKU / "clicker.py"):
            self.assertFalse(runner.uses_capture(path), path)


class ImportTest(unittest.TestCase):
    def test_script_imports_collects_top_level_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "sample.py"
            script.write_text(
                "import os\n"
                "import numpy as np\n"
                "from pathlib import Path\n"
                "import local_helper\n"
                "from . import sibling\n",
                encoding="utf-8",
            )
            (Path(tmp) / "local_helper.py").write_text("", encoding="utf-8")
            self.assertEqual(
                runner.script_imports(script),
                ["local_helper", "numpy", "os", "pathlib"],
            )

    def test_script_imports_survives_syntax_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "broken.py"
            script.write_text("def f(:\n", encoding="utf-8")
            self.assertEqual(runner.script_imports(script), [])

    def test_resolve_import_statuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "local_helper.py").write_text("", encoding="utf-8")
            (base / "apkg").mkdir()
            self.assertEqual(runner.resolve_import("os", base)[0], "stdlib")
            self.assertEqual(runner.resolve_import("local_helper", base), ("本地", "local_helper.py"))
            self.assertEqual(runner.resolve_import("apkg", base), ("本地", "apkg/"))
            self.assertEqual(runner.resolve_import("numpy", base)[0], "已安装")
            self.assertEqual(runner.resolve_import("definitely_missing_xyz", base)[0], "缺失")


class ListAndCheckTest(unittest.TestCase):
    def test_list_scripts_excludes_libraries_and_includes_routes(self):
        rels = {rel for _, rel, _ in runner.list_scripts()}
        self.assertIn("haikuScripts/s2_clp.py", rels)
        self.assertIn("marcoRecorder/adele-truth1.py", rels)
        self.assertIn("auto-maple/main.py", rels)
        self.assertNotIn("maplebot/runner.py", rels)
        self.assertNotIn("haikuScripts/catms/cube_washer.py", rels)
        self.assertNotIn("haikuScripts/khali/commands.py", rels)
        self.assertGreater(len(rels), 30)

    def test_every_script_has_a_known_kind(self):
        for kind, rel, _ in runner.list_scripts():
            self.assertIn(kind, runner.KIND_ORDER, rel)

    def test_check_sources_passes(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = runner.check_sources()
        self.assertEqual(rc, 0, out.getvalue())
        self.assertIn("rune.py", out.getvalue())  # 已知坏文件会被单独列出


class FindGameWindowTest(unittest.TestCase):
    def test_returns_matching_title(self):
        with mock.patch("maplebot.win32.find_ready_window", side_effect=lambda t: 1 if t == "MapleStory" else 0):
            self.assertEqual(runner.find_game_window(timeout=0), "MapleStory")

    def test_returns_none_when_nothing_matches(self):
        with mock.patch("maplebot.win32.find_ready_window", return_value=0):
            self.assertIsNone(runner.find_game_window(timeout=0))

    def test_respects_explicit_title_list(self):
        seen = []

        def fake(title):
            seen.append(title)
            return 1 if title == "MapleStory" else 0

        with mock.patch("maplebot.win32.find_ready_window", side_effect=fake):
            self.assertEqual(runner.find_game_window(timeout=0, titles=["MapleStory"]), "MapleStory")
        self.assertEqual(seen, ["MapleStory"])


class CliDispatchTest(unittest.TestCase):
    def test_list_returns_zero(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(runner.main(["--list"]), 0)
        self.assertIn("s2_clp.py", out.getvalue())

    def test_no_arguments_returns_usage_error(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(runner.main([]), 2)
        self.assertIn("usage", out.getvalue().lower())

    def test_dry_run_returns_zero(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(runner.main(["--dry-run", "--script", "s2_clp"]), 0)
        text = out.getvalue()
        self.assertIn("import 检查", text)
        self.assertNotIn("!!", text)

    def test_dry_run_for_non_capture_script(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(runner.main(["--dry-run", "--script", "scriptWriter"]), 0)
        self.assertIn("不使用截屏", out.getvalue())

    def test_check_returns_zero(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(runner.main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
