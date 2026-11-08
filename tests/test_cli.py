"""run.py 的端到端 CLI 测试（子进程，不碰游戏）。

覆盖：参数分派、退出码、--list / --check / --dry-run、找不到脚本的提示、
以及 --stop-after 能停住真正的死循环脚本。
"""

import unittest

from tests.helpers import ROOT, run_cli


class CliTest(unittest.TestCase):
    def test_no_arguments_prints_usage_and_fails(self):
        result = run_cli()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("usage", result.stdout.lower())

    def test_list(self):
        result = run_cli("--list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("haikuScripts/s2_clp.py", result.stdout)
        self.assertIn("marcoRecorder/adele-truth1.py", result.stdout)
        self.assertIn("生成器", result.stdout)
        self.assertNotIn("maplebot/runner.py", result.stdout)

    def test_check(self):
        result = run_cli("--check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("rune.py", result.stdout)

    def test_dry_run_reports_missing_imports_clearly(self):
        result = run_cli("--dry-run", "--script", "s2_clp")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("import 检查", result.stdout)
        self.assertNotIn("!!", result.stdout)
        self.assertIn("ok ", result.stdout)

    def test_dry_run_for_mcr_generator_skips_window(self):
        result = run_cli("--dry-run", "--script", "scriptWriter")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("不使用截屏", result.stdout)

    def test_unknown_script_suggests_alternative(self):
        result = run_cli("--script", "s2_clpp")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("s2_clp", result.stdout + result.stderr)

    def test_stop_after_stops_infinite_loop(self):
        result = run_cli(
            "--script", "loop_forever",
            "--dir", "tests/fixtures",
            "--stop-after", "1",
            "--no-stop-key",
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[fixture] started", result.stdout)
        self.assertIn("已停止", result.stdout)

    def test_stop_after_zero_is_immediate(self):
        result = run_cli(
            "--script", "loop_forever",
            "--dir", "tests/fixtures",
            "--stop-after", "0.001",
            "--no-stop-key",
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class DryRunOutputTest(unittest.TestCase):
    def test_dry_run_lists_resolved_paths(self):
        result = run_cli("--dry-run", "--script", "khali_library_1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(str(ROOT / "haikuScripts" / "khali_library_1.py"), result.stdout)
        self.assertIn("急停键", result.stdout)

    def test_window_option_is_echoed(self):
        result = run_cli("--dry-run", "--script", "s2_clp", "--window", "MapleStory")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("MapleStory", result.stdout)

    def test_no_stop_key_is_echoed(self):
        result = run_cli("--dry-run", "--script", "s2_clp", "--no-stop-key")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("已关闭", result.stdout)


if __name__ == "__main__":
    unittest.main()
