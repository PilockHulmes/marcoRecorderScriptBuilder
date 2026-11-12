"""maplebot.cube 的单元测试：属性解析、等级徽章、保留判定。"""

import unittest

import cv2
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


    def test_per_level_with_dropped_letter(self):
        # 真实 OCR 结果：DEX 被认成 DE，繁体被识别成简体
        self.assertEqual(cube.parse_line("以角色等级為准每9级DE+2"), ("DEX", "perlevel", 2))

    def test_stat_aliases(self):
        self.assertEqual(cube.normalize_stat("de"), "DEX")
        self.assertEqual(cube.normalize_stat("LU"), "LUK")
        self.assertEqual(cube.normalize_stat("st"), "STR")


    def test_fuzzy_stat_names_from_real_ocr(self):
        # 这几种都是真实洗魔方时 OCR 读出来的错拼
        self.assertEqual(cube.parse_line("全性 +5%"), ("ALL", "pct", 5))
        self.assertEqual(cube.parse_line("ETR +18"), ("STR", "flat", 18))
        self.assertEqual(cube.parse_line("DEK +2"), ("DEX", "flat", 2))

    def test_unknown_lines_stay_other(self):
        for text in ("MAXMP +11%", "道具掉落率+5%", "物理攻擎力 +16", "MaxHP +300"):
            self.assertEqual(cube.parse_line(text)[0], "OTHER", text)

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




class FakeOCR:
    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = 0

    def ocr(self, image):
        self.calls += 1
        text = self.texts[min(self.calls - 1, len(self.texts) - 1)]
        if not text:
            return []
        box = [[0, 0], [10, 0], [10, 10], [0, 10]]
        return [[[box, (text, 0.99)]]]


class FakeKeys:
    def __init__(self):
        self.taps = []

    def tap(self, key, hold=0.04):
        self.taps.append(key)


class FakeGrab:
    def __init__(self, frames):
        self.frames = list(frames)
        self.index = 0

    def __call__(self):
        frame = self.frames[min(self.index, len(self.frames) - 1)]
        self.index += 1
        return frame


def make_frame(selected=False, badges=True):
    frame = np.zeros((807, 1382, 3), np.uint8)
    x0, y0, x1, y1 = cube.box_pixels(frame, cube.PINK_CUBE_BOX)
    if selected:
        cv2.rectangle(frame, (x0, y0), (x1, y1), (255, 255, 0), 3)   # 青色（BGR）
    if badges:
        for badge, _text in cube.row_boxes(frame):
            bx, by, bw, bh = badge
            cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 255, 204), -1)
    return frame


class SelectedTest(unittest.TestCase):
    def test_cyan_border_means_selected(self):
        self.assertTrue(cube.is_selected(make_frame(selected=True)))

    def test_plain_frame_is_not_selected(self):
        self.assertFalse(cube.is_selected(make_frame(selected=False)))

    def test_centres(self):
        frame = make_frame()
        self.assertEqual(cube.box_center(frame, cube.PINK_CUBE_BOX), (225, 540))
        self.assertEqual(cube.box_center(frame, cube.RESET_BTN_BOX), (357, 722))


class RollerTest(unittest.TestCase):
    def make(self, frames, texts, main="LUK", header="珍貴附加方塊"):
        self.clicks = []
        self.keys = FakeKeys()
        self.grab = FakeGrab(frames)
        roller = cube.CubeRoller(
            grab=self.grab,
            click=lambda x, y: self.clicks.append((x, y)),
            key_api=self.keys,
            ocr=FakeOCR([header] + list(texts)),
            sleep=lambda _s: None,
            main=main,
        )
        return roller

    def test_roll_once_selects_clicks_and_enters(self):
        frames = [make_frame(False), make_frame(False), make_frame(True), make_frame(True), make_frame(True)]
        roller = self.make(frames, ["珍貴附加方塊", "LUK +9%", "全屬性 +6%", "每9級 LUK +2"],
                           header="恢復附加方塊")
        lines = roller.roll_once()
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0].stat, "LUK")
        self.assertEqual(self.clicks[0], (int(cube.SLOT_X[0] * 1382), 540))       # 点第一个槽位
        self.assertEqual(self.clicks[1], (357, 722))       # 点重新設定
        self.assertEqual(self.keys.taps, ["enter"])

    def test_already_selected_skips_cube_click(self):
        frames = [make_frame(True)] * 4
        roller = self.make(frames, ["LUK +9%", "LUK +8%", "LUK +7%"])
        roller.roll_once()
        self.assertEqual(self.clicks, [(357, 722)])        # 已选中时只点重新設定

    def test_failure_to_select_raises(self):
        frames = [make_frame(False)] * 3
        roller = self.make(frames, ["LUK +9%"] * 8, header="恢復附加方塊")
        with self.assertRaises(cube.RollError):
            roller.roll_once()

    def test_run_until_stops_and_presses_esc(self):
        frames = [make_frame(True)] * 8
        roller = self.make(frames, ["LUK +9%", "LUK +8%", "LUK +7%"])
        ok, _ = roller.run_until(max_rolls=5)
        self.assertTrue(ok)
        self.assertIn("esc", self.keys.taps)
        self.assertEqual(roller.rolls, 1)


class ReadLinesTest(unittest.TestCase):
    def test_retries_right_half_when_full_line_fails(self):
        # 整行认不出时，裁右半段重试："STR +2" 就读出来了
        ocr = FakeOCR(["以角色等级為准每9级", "STR +2", "LUK +9%", "全屬性 +6%"])
        lines = cube.read_lines(np.zeros((807, 1382, 3), np.uint8), ocr=ocr)
        self.assertEqual(len(lines), 3)
        self.assertEqual((lines[0].stat, lines[0].kind, lines[0].value), ("STR", "perlevel", 2))
        self.assertEqual(lines[1].stat, "LUK")
        self.assertEqual(lines[2].stat, "ALL")

    def test_no_retry_when_first_read_succeeds(self):
        ocr = FakeOCR(["LUK +9%", "LUK +8%", "LUK +7%"])
        cube.read_lines(np.zeros((807, 1382, 3), np.uint8), ocr=ocr)
        self.assertEqual(ocr.calls, 3)


if __name__ == "__main__":
    unittest.main()
