import time
import unittest

from maplebot import activity


class ActivityTierTest(unittest.TestCase):
    def make(self, idle):
        return activity.Activity(get_idle=lambda: idle)

    def test_no_game_means_off(self):
        act = self.make(0)
        self.assertEqual(act.update(0.0, game_running=False), activity.TIER_OFF)
        self.assertIsNone(activity.Activity.poll_interval(activity.TIER_OFF))

    def test_shop_open_is_always_active(self):
        act = self.make(3600)            # 一小时没输入
        self.assertEqual(act.update(0.0, shop_open=True), activity.TIER_ACTIVE)
        self.assertEqual(activity.Activity.poll_interval(activity.TIER_ACTIVE), 1.0)

    def test_recent_input_is_active(self):
        self.assertEqual(self.make(10).update(0.0), activity.TIER_ACTIVE)
        self.assertEqual(self.make(120).update(0.0), activity.TIER_ACTIVE)

    def test_five_minutes_is_running_tier(self):
        self.assertEqual(self.make(299).update(0.0), activity.TIER_RUNNING)
        self.assertEqual(activity.Activity.poll_interval(activity.TIER_RUNNING), 3.0)

    def test_fifteen_minutes_is_idle_tier(self):
        self.assertEqual(self.make(600).update(0.0), activity.TIER_IDLE)
        self.assertEqual(activity.Activity.poll_interval(activity.TIER_IDLE), 15.0)

    def test_over_fifteen_minutes_is_away(self):
        self.assertEqual(self.make(901).update(0.0), activity.TIER_AWAY)
        self.assertEqual(activity.Activity.poll_interval(activity.TIER_AWAY), 60.0)

    def test_map_change_promotes_to_active_even_if_idle(self):
        act = self.make(3600)
        self.assertEqual(act.update(0.0, map_changed=True), activity.TIER_ACTIVE)

    def test_moving_on_the_minimap_counts_as_activity(self):
        act = self.make(3600)
        act.update(0.0, position=(0.5, 0.5))
        self.assertEqual(act.update(0.1, position=(0.6, 0.5)), activity.TIER_ACTIVE)

    def test_tiny_jitter_is_not_movement(self):
        act = self.make(3600)
        act.update(0.0, position=(0.500, 0.500))
        # 只抖了 0.005：算原地不动
        self.assertEqual(act.update(0.1, position=(0.505, 0.500)), activity.TIER_AWAY)

    def test_recovers_immediately_when_input_returns(self):
        idle = {"value": 3600}
        act = activity.Activity(get_idle=lambda: idle["value"])
        self.assertEqual(act.update(0.0), activity.TIER_AWAY)
        idle["value"] = 1.0              # 玩家摸了一下鼠标
        self.assertEqual(act.update(1.0), activity.TIER_ACTIVE)

    def test_system_idle_reads_a_sane_value(self):
        seconds = activity.system_idle_seconds()
        self.assertGreaterEqual(seconds, 0.0)
        self.assertLess(seconds, 86400.0)


if __name__ == "__main__":
    unittest.main()
