"""maplebot.cube 的单元测试：属性解析、等级徽章、保留判定。"""

import unittest

import numpy as np

from maplebot import cube


class ParseLineTest(unittest.TestCase):
    def test_single_stat_percent(self):
        self.assertEqual(cube.parse_line("LUK +9%"), ("LUK", "pct", 9))
        self.assertEqual(cube.parse_line("STR +8%"), ("STR", "pct", 8))

    def test_all_stat_percent(self):
        self.assertEqual(cube.parse_line("全屬性 +7%"), ("ALL", "pct", 7))
        self.assertEqual(cube.parse_line("全属性 +5%"), ("ALL", "pct", 5))

    def test_flat_value(self):
        self.assertEqual(cube.parse_line("STR +20"), ("STR", "flat", 20))

    def test_per_level(self):
        self.assertEqual(cube.parse_line("以角色等級為準每9級 LUK +2"), ("LUK", "perlevel", 2))
        self.assertEqual(cube.parse_line("每 9 級STR+1"), ("STR", "perlevel", 1))

    def test_fullwidth_and_spaces(self):
        self.assertEqual(cube.parse_line("LUK ＋９％"), ("LUK", "pct", 9))

    def test_garbage(self):
        self.assertEqual(cube.parse_line(""), ("", "", 0))
        self.assertEqual(cube.parse_line("無法辨識"), ("", "", 0))


class GradeTest(unittest.TestCase):
    def test_legendary(self):
        self.assertEqual(cube.grade_from_badge((0, 255, 204)), "L")   # 实测 L 徽章

    def test_unique(self):
        self.assertEqual(cube.grade_from_badge((0, 204, 255)), "U")   # 实测 U 徽章

    def test_background_is_unknown(self):
        self.assertEqual(cube.grade_from_badge((30, 30, 30)), "?")


class JudgeTest(unittest.TestCase):
    def line(self, text, grade="L"):
        stat, kind, value = cube.parse_line(text)
        return cube.PotentialLine(raw=text, grade=grade, stat=stat, kind=kind, value=value)

    def test_luk_triple_is_keep(self):
        lines = [self.line("LUK +9%"), self.line("全屬性 +6%"), self.line("每9級 LUK +2", "U")]
        keep, _ = cube.judge(lines, main="LUK")
        self.assertTrue(keep)

    def test_luk_with_useless_line_is_not_keep(self):
        lines = [self.line("LUK +9%"), self.line("MaxHP +11%"), self.line("LUK +8%")]
        keep, reason = cube.judge(lines, main="LUK")
        self.assertFalse(keep)
        self.assertIn("不满足", reason)

    def test_flat_lines_are_not_useful(self):
        lines = [self.line("LUK +20"), self.line("LUK +9%"), self.line("LUK +8%")]
        keep, _ = cube.judge(lines, main="LUK")
        self.assertFalse(keep)

    def test_per_level_one_is_not_useful(self):
        lines = [self.line("每9級 LUK +1"), self.line("LUK +9%"), self.line("LUK +8%")]
        self.assertFalse(cube.judge(lines, main="LUK")[0])

    def test_other_stat_triple_legendary_is_keep(self):
        lines = [self.line("STR +8%", "L"), self.line("每9級 STR +2", "L"), self.line("STR +6%", "L")]
        keep, reason = cube.judge(lines, main="LUK")
        self.assertTrue(keep, reason)

    def test_other_stat_with_unique_is_not_keep(self):
        lines = [self.line("STR +8%", "L"), self.line("STR +6%", "U"), self.line("STR +8%", "L")]
        self.assertFalse(cube.judge(lines, main="LUK")[0])

    def test_mixed_stats_not_keep(self):
        lines = [self.line("STR +8%", "L"), self.line("DEX +8%", "L"), self.line("STR +6%", "L")]
        self.assertFalse(cube.judge(lines, main="LUK")[0])

    def test_wrong_line_count(self):
        self.assertFalse(cube.judge([self.line("LUK +9%")], main="LUK")[0])

    def test_unparsed_line_blocks_keep(self):
        bad = cube.PotentialLine(raw="???", grade="L", stat="", kind="", value=0)
        lines = [self.line("LUK +9%"), bad, self.line("LUK +8%")]
        self.assertFalse(cube.judge(lines, main="LUK")[0])


class RowBoxTest(unittest.TestCase):
    def test_boxes_scale_with_frame(self):
        small = np.zeros((807, 1382, 3), np.uint8)
        big = np.zeros((1614, 2764, 3), np.uint8)
        a = cube.row_boxes(small)[0]
        b = cube.row_boxes(big)[0]
        self.assertAlmostEqual(a[0][0] * 2, b[0][0], delta=2)
        self.assertAlmostEqual(a[1][1] * 2, b[1][1], delta=2)

    def test_three_rows_in_order(self):
        frame = np.zeros((807, 1382, 3), np.uint8)
        rows = cube.row_boxes(frame)
        self.assertEqual(len(rows), 3)
        ys = [row[1][1] for row in rows]
        self.assertEqual(ys, sorted(ys))


if __name__ == "__main__":
    unittest.main()
