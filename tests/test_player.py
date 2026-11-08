"""maplebot.player 的单元测试：黄点检测 + 跟踪。

用真实截图裁出来的固定样本（tests/fixtures/minimap_*.png）+ 合成画面。
真实截图里玩家位置：rune_icon / rune_buff 都约 (43,118) / (35,142)，
rune_example 约 (95,136)。
"""

import unittest

import cv2
import numpy as np

from maplebot import minimap, player
from tests.helpers import ROOT

FIXTURES = ROOT / "tests" / "fixtures"
YELLOW = (0, 239, 254)     # BGR，实测玩家黄点
GREEN = (0, 255, 0)        # NPC / 传送点
RED = (0, 0, 255)          # 其他玩家（用户确认是红圈）
WHITE = (255, 255, 255)

FRAME = (600, 800)         # (h, w)


def frame_with(markers, size=FRAME, bg=(13, 13, 25)):
    """造一张深色画面，按 (x, y, color) 画"彩色点 + 白圈"。"""
    frame = np.full((size[0], size[1], 3), bg, np.uint8)
    for x, y, color in markers:
        cv2.circle(frame, (x, y), 3, color, -1)
        cv2.circle(frame, (x, y), 4, WHITE, 1)
    return frame


def box_for(frame, inset=3):
    h, w = frame.shape[:2]
    return minimap.MinimapBox(0, 0, w, h).inner(inset)


class MarkerDetectionTest(unittest.TestCase):
    def test_finds_synthetic_player(self):
        frame = frame_with([(100, 120, YELLOW)])
        found = player.find_player(frame, box_for(frame))
        self.assertIsNotNone(found)
        self.assertLessEqual(abs(found.x - 100), 2)
        self.assertLessEqual(abs(found.y - 120), 2)

    def test_green_npc_is_rejected(self):
        frame = frame_with([(100, 120, GREEN)])
        self.assertEqual(player.find_candidates(frame, box_for(frame)), [])

    def test_red_other_player_is_rejected(self):
        frame = frame_with([(100, 120, RED)])
        self.assertEqual(player.find_candidates(frame, box_for(frame)), [])

    def test_yellow_without_white_ring_is_rejected(self):
        frame = np.full((FRAME[0], FRAME[1], 3), (13, 13, 25), np.uint8)
        cv2.rectangle(frame, (100, 120), (106, 126), YELLOW, -1)   # 只有黄块，没有白圈
        self.assertEqual(player.find_candidates(frame, box_for(frame)), [])

    def test_dark_yellow_platform_is_rejected(self):
        # 平台那种暗黄（V≈70）不该被当成玩家
        frame = frame_with([(100, 120, (3, 32, 76))])
        self.assertEqual(player.find_candidates(frame, box_for(frame)), [])

    def test_multiple_candidates_sorted_by_score(self):
        frame = frame_with([(100, 120, YELLOW), (300, 120, YELLOW)])
        candidates = player.find_candidates(frame, box_for(frame))
        self.assertEqual(len(candidates), 2)
        self.assertGreaterEqual(candidates[0].score, candidates[1].score)

    def test_empty_frame(self):
        self.assertEqual(player.find_candidates(None), [])
        self.assertEqual(player.find_candidates(np.zeros((0, 0, 3), np.uint8)), [])
        self.assertIsNone(player.find_player(np.zeros((FRAME[0], FRAME[1], 3), np.uint8), box_for(np.zeros((FRAME[0], FRAME[1], 3), np.uint8))))


class RealScreenshotTest(unittest.TestCase):
    def load(self, name):
        frame = cv2.imread(str(FIXTURES / name))
        self.assertIsNotNone(frame, f"fixture 缺失：{name}")
        return frame

    def test_finds_player_on_minimap_fixture(self):
        frame = self.load("minimap_rune.png")
        found = player.find_player(frame)
        self.assertIsNotNone(found)
        # 实测 (43, 118)
        self.assertLessEqual(abs(found.x - 43), 3, found)
        self.assertLessEqual(abs(found.y - 118), 3, found)

    def test_same_player_position_without_rune(self):
        frame = self.load("minimap_no_rune.png")
        found = player.find_player(frame)
        self.assertIsNotNone(found)
        # 这张 fixture 来自 rune_buff.png，玩家在 (35, 142)
        self.assertLessEqual(abs(found.x - 35), 3, found)
        self.assertLessEqual(abs(found.y - 142), 3, found)

    def test_score_margin_vs_background(self):
        frame = self.load("minimap_rune.png")
        found = player.find_player(frame)
        self.assertGreaterEqual(found.ring, player.RING_RATIO_MIN)


class FakeClock:
    def __init__(self, now=0.0):
        self.now = float(now)

    def __call__(self):
        return self.now

    def advance(self, dt):
        self.now += float(dt)
        return self.now


class TrackerTest(unittest.TestCase):
    def make_tracker(self):
        clock = FakeClock()
        return player.PlayerTracker(clock=clock, stale_seconds=0.35), clock

    def test_first_update_snaps(self):
        frame = frame_with([(100, 120, YELLOW)])
        tracker, _ = self.make_tracker()
        pos = tracker.update(frame, box_for(frame))
        self.assertEqual(pos, (100.0, 120.0))
        self.assertFalse(tracker.stale)

    def test_occlusion_keeps_last_position_then_expires(self):
        tracker, clock = self.make_tracker()
        frame = frame_with([(100, 120, YELLOW)])
        tracker.update(frame, box_for(frame))
        blank = frame_with([])

        # 遮挡 0.2s：位置保留，还不算 stale
        clock.advance(0.2)
        self.assertEqual(tracker.update(blank, box_for(frame)), (100.0, 120.0))
        self.assertFalse(tracker.stale)
        self.assertEqual(tracker.misses, 1)

        # 超过 stale_seconds：位置变成 None
        clock.advance(0.4)
        self.assertIsNone(tracker.update(blank, box_for(frame)))
        self.assertTrue(tracker.stale)

    def test_choose_nearby_candidate_when_two_exist(self):
        tracker, clock = self.make_tracker()
        first = frame_with([(100, 120, YELLOW)])
        tracker.update(first, box_for(first))
        clock.advance(0.1)

        both = frame_with([(103, 120, YELLOW), (300, 120, YELLOW)])
        tracker.update(both, box_for(both))
        self.assertLess(abs(tracker.position[0] - 103), 10, tracker.position)

    def test_far_jump_is_snapped_and_counted(self):
        tracker, clock = self.make_tracker()
        first = frame_with([(100, 120, YELLOW)])
        tracker.update(first, box_for(first))
        clock.advance(0.1)

        far = frame_with([(500, 400, YELLOW)])
        tracker.update(far, box_for(far))
        self.assertEqual(tracker.position, (500.0, 400.0))
        self.assertEqual(tracker.jumps, 1)

    def test_smoothing_reduces_jitter(self):
        tracker, clock = self.make_tracker()
        box = box_for(frame_with([]))
        for x in (100, 100):
            tracker.update(frame_with([(x, 120, YELLOW)]), box)
            clock.advance(0.1)
        # 突然抖一下 +3px：平滑后的位置应该落在中间
        tracker.update(frame_with([(103, 120, YELLOW)]), box)
        self.assertGreater(tracker.position[0], 100.0)
        self.assertLess(tracker.position[0], 103.0)

    def test_reset(self):
        tracker, _ = self.make_tracker()
        frame = frame_with([(100, 120, YELLOW)])
        tracker.update(frame, box_for(frame))
        tracker.reset()
        self.assertIsNone(tracker.position)
        self.assertIsNone(tracker.raw)
        self.assertTrue(tracker.stale)

    def test_missing_minimap_counts_as_miss(self):
        tracker, clock = self.make_tracker()
        blank = np.zeros(FRAME + (3,), np.uint8)
        clock.advance(1.0)
        self.assertIsNone(tracker.update(blank))
        self.assertEqual(tracker.misses, 1)


if __name__ == "__main__":
    unittest.main()
