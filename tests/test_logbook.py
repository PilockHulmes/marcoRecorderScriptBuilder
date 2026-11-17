import os
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from maplebot import logbook


class LogbookTest(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.dir = Path(self.folder.name)
        self.stdout = sys.stdout

    def tearDown(self):
        logbook.close()
        sys.stdout = self.stdout
        self.folder.cleanup()

    def read(self, path):
        return Path(path).read_text(encoding="utf-8")

    def test_setup_creates_a_log_file_with_a_header(self):
        path = logbook.setup(self.dir)
        text = self.read(path)
        self.assertTrue(path.exists())
        self.assertEqual(path.parent, self.dir)
        self.assertIn("[日誌]", text)
        self.assertIn("不截屏", text)

    def test_print_goes_into_the_log(self):
        path = logbook.setup(self.dir)
        print("商店讀取失敗")
        self.assertIn("商店讀取失敗", self.read(path))

    def test_log_event_writes_fields(self):
        path = logbook.setup(self.dir)
        logbook.log_event("標定", 尺度=1.4056, 得分=0.966)
        text = self.read(path)
        self.assertIn("[標定]", text)
        self.assertIn("尺度=1.4056", text)
        self.assertIn("得分=0.966", text)

    def test_exception_hook_writes_traceback(self):
        path = logbook.setup(self.dir)
        try:
            raise ValueError("壞掉了")
        except ValueError:
            logbook._excepthook(*sys.exc_info())
        text = self.read(path)
        self.assertIn("[異常]", text)
        self.assertIn("ValueError", text)
        self.assertIn("Traceback", text)

    def test_rotation_keeps_only_the_newest_files(self):
        for index in range(4):
            old = self.dir / f"assistant-2026010{index}-000000.log"
            old.write_text("old", encoding="utf-8")
            stamp = time.time() - (10 - index) * 60
            os.utime(old, (stamp, stamp))
        path = logbook.setup(self.dir, keep=2)
        remaining = sorted(item.name for item in self.dir.glob("assistant-*.log"))
        self.assertEqual(len(remaining), 2)
        self.assertIn(path.name, remaining)

    def test_close_restores_stdout(self):
        logbook.setup(self.dir)
        logbook.close()
        self.assertIs(sys.stdout, self.stdout)

    def test_log_lines_are_flushed_immediately(self):
        path = logbook.setup(self.dir)
        logbook.log_event("崩潰前", 句柄="最後一行")
        self.assertIn("最後一行", self.read(path))


if __name__ == "__main__":
    unittest.main()
