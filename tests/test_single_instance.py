import uuid
import unittest

from maplebot import single_instance


class SingleInstanceTest(unittest.TestCase):
    def setUp(self):
        # 每个用例用独立名字，避免和真实运行的实例互相影响
        self.name = "Local\\MapleTrade.Test." + uuid.uuid4().hex

    def test_second_acquire_fails(self):
        first = single_instance.SingleInstance(self.name)
        self.assertTrue(first.acquire())
        second = single_instance.SingleInstance(self.name)
        self.assertFalse(second.acquire())
        second.release()
        first.release()

    def test_release_allows_acquire_again(self):
        first = single_instance.SingleInstance(self.name)
        self.assertTrue(first.acquire())
        first.release()
        again = single_instance.SingleInstance(self.name)
        self.assertTrue(again.acquire())
        again.release()

    def test_acquire_is_idempotent_within_one_object(self):
        item = single_instance.SingleInstance(self.name)
        self.assertTrue(item.acquire())
        self.assertTrue(item.acquire())
        item.release()

    def test_context_manager_releases(self):
        with single_instance.SingleInstance(self.name) as item:
            self.assertTrue(item.acquire())
        again = single_instance.SingleInstance(self.name)
        self.assertTrue(again.acquire())
        again.release()

    def test_activate_missing_window_returns_false(self):
        self.assertFalse(
            single_instance.activate_running_window("不存在的窗口标题-" + uuid.uuid4().hex))


if __name__ == "__main__":
    unittest.main()
