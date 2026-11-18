"""原生尺度数字模板（1920 那套 12px 细体 / 14px 粗体）。

背景：`frame.canonical()` 会把 1920 画面缩回 1366，8px 的位图字体缩完会掉列，
数字认错（00:57 读成 01:00）。所以另存了一套"原生尺度"模板，
`session` 在标定尺度 ≈ 画面宽度比时用它们直接从原图读。
"""

import unittest

import cv2
import numpy as np

from maplebot import digits, trade


def _load_native(family, digit):
    table = digits.load()
    return table[family][digit]


def _compose(frame, text, glyph_family, x0, y0, gap=3, color=(0, 210, 255)):
    """把 text 里的数字用模板拼到 frame 的 (x0, y0)，返回每位的 x 位置。"""
    x = x0
    positions = []
    for ch in text:
        if ch.isdigit():
            glyph = np.array(_load_native(glyph_family, ch)[0], dtype=np.uint8)
            mask = glyph > 127
            h, w = mask.shape
            region = frame[y0:y0 + h, x:x + w]
            region[mask] = color
            frame[y0:y0 + h, x:x + w] = region
            positions.append(x)
            x += w + gap
        else:                      # 冒号：留白
            x += 6
    return positions


class FamilySelectionTest(unittest.TestCase):
    def test_scaled_frames_use_native_family(self):
        self.assertEqual(digits.family_for("thin", 1.4056), "thin_native")
        self.assertEqual(digits.family_for("fat", 1.5625), "fat_native")

    def test_base_frames_keep_original_family(self):
        self.assertEqual(digits.family_for("thin", 1.0), "thin")
        self.assertEqual(digits.family_for("thin", None), "thin")
        self.assertEqual(digits.family_for("fat", 1.2), "fat")

    def test_native_families_cover_all_digits(self):
        table = digits.load()
        for family in ("thin_native", "fat_native"):
            self.assertEqual(sorted(table[family]), list("0123456789"), family)


class NativeCountdownTest(unittest.TestCase):
    def _frame(self):
        frame = np.zeros((1080, 1920, 3), np.uint8)
        frame[:] = (40, 35, 30)
        # COUNTDOWN_BOX 的窗口坐标 (580,252) -> 原生 (814,309)
        _compose(frame, "02:25", "fat_native", 829, 316)
        return frame

    def test_reads_from_native_frame(self):
        frame = self._frame()
        self.assertEqual(trade.read_row_countdown(frame, native=(frame, 1.4056)), "02:25")

    def test_without_native_it_reads_the_same_box_at_base_scale(self):
        # 同一张图不传 native 时按 1366 的框裁 —— 裁到空白，读不到（说明 native 真的在起作用）
        frame = self._frame()
        self.assertEqual(trade.read_row_countdown(frame), "")


class NativePriceTest(unittest.TestCase):
    def test_reads_price_from_native_frame(self):
        frame = np.zeros((1080, 1920, 3), np.uint8)
        frame[:] = (40, 35, 30)
        # 第 0 行买价的窗口坐标 (535, 321) -> 原生 (750, 406)
        _compose(frame, "12", "thin_native", 762, 412)
        view = frame
        value = trade._read_price(view, trade.ROW_TOPS[0], trade.BUY_DY,
                                  native=(frame, 1.4056))
        self.assertEqual(value, 12)


if __name__ == "__main__":
    unittest.main()
