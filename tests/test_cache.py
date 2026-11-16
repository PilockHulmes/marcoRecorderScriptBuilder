"""像素摘要缓存：命中要省 OCR，失效条件要可靠。"""

import time
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

from maplebot import trade

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "shop_frame.png"


def load_frame():
    return cv2.imdecode(np.fromfile(str(FIXTURE), dtype=np.uint8), cv2.IMREAD_COLOR)


def scroll_frame(frame, pixels=33):
    """把列表区整体上移，模拟滚轮滚动。"""
    x, y, w, h = trade.LIST_BOX
    shifted = frame.copy()
    region = frame[y:y + h, x:x + w].copy()
    shifted[y:y + h, x:x + w] = np.roll(region, -pixels, axis=0)
    return shifted


class RowsCacheTest(unittest.TestCase):
    def setUp(self):
        self.frame = load_frame()
        self.cache = trade.FrameCache()
        self.deadline = time.time() + 150
        trade.read_rows(self.frame)          # 预热 OCR 模型

    def counting(self, frame, **kwargs):
        """数一数 read_rows 内部读了几次价格（缓存命中时应当为 0）。"""
        calls = []
        original = trade._read_price

        def wrapper(*args, **kw):
            calls.append(1)
            return original(*args, **kw)

        with mock.patch.object(trade, "_read_price", side_effect=wrapper):
            rows = trade.read_rows(frame, **kwargs)
        return rows, len(calls)

    def test_second_read_hits_cache_and_skips_ocr(self):
        first, calls1 = self.counting(self.frame, cache=self.cache,
                                      cache_tag="kobi_1", deadline=self.deadline)
        second, calls2 = self.counting(self.frame, cache=self.cache,
                                       cache_tag="kobi_1", deadline=self.deadline)
        self.assertGreater(calls1, 0)
        self.assertEqual(calls2, 0, "第二次不该再 OCR")
        self.assertEqual([r.buy_price for r in first], [r.buy_price for r in second])
        self.assertEqual([r.sell_price for r in first], [r.sell_price for r in second])

    def test_refresh_invalidates_cache(self):
        self.counting(self.frame, cache=self.cache, cache_tag="kobi_1",
                      deadline=self.deadline)
        _, calls = self.counting(self.frame, cache=self.cache, cache_tag="kobi_1",
                                 deadline=self.deadline + 200)
        self.assertGreater(calls, 0, "商店刷新后必须重读价格")

    def test_scroll_invalidates_cache(self):
        self.counting(self.frame, cache=self.cache, cache_tag="kobi_1",
                      deadline=self.deadline)
        _, calls = self.counting(scroll_frame(self.frame), cache=self.cache,
                                 cache_tag="kobi_1", deadline=self.deadline)
        self.assertGreater(calls, 0, "滚动后必须重读")

    def test_different_merchant_does_not_share_cache(self):
        self.counting(self.frame, cache=self.cache, cache_tag="kobi_1",
                      deadline=self.deadline)
        _, calls = self.counting(self.frame, cache=self.cache, cache_tag="dour_4",
                                 deadline=self.deadline)
        self.assertGreater(calls, 0, "换商人不能用别人的缓存")


class CacheBoundsTest(unittest.TestCase):
    def test_lru_does_not_grow_forever(self):
        cache = trade.FrameCache(max_entries=3)
        for index in range(10):
            cache.put(("k", index), index)
        self.assertEqual(len(cache), 3)
        self.assertIsNone(cache.get(("k", 0)))
        self.assertEqual(cache.get(("k", 9)), 9)


if __name__ == "__main__":
    unittest.main()
