import unittest

from maplebot import sync


BASE = 1_800_000_000.0


def record(merchant_id="dour_4", rows=None, t=BASE, r=300.0, writer="me", rev=1,
           map_name="孤獨的沙漠-1"):
    rows = rows or {"water|sell": {"p": 19, "t": t, "r": r}}
    return sync.make_record(merchant_id, map_name, writer, rev, rows)


class LocalStore:
    """测试用的本地存储：就是一张 dict。"""

    def __init__(self):
        self.records = {}

    def get(self, merchant_id):
        return self.records.get(merchant_id)

    def apply(self, merchant_id, merged):
        self.records[merchant_id] = merged


class MergeTest(unittest.TestCase):
    def test_newer_row_wins(self):
        local = record(rows={"water|sell": {"p": 19, "t": BASE, "r": 300}})
        remote = record(writer="other",
                        rows={"water|sell": {"p": 21, "t": BASE + 10, "r": 300}})
        merged = sync.merge_records(local, remote, BASE + 20)
        self.assertEqual(merged["rows"]["water|sell"]["p"], 21)

    def test_older_row_does_not_overwrite(self):
        local = record(rows={"water|sell": {"p": 21, "t": BASE + 10, "r": 300}})
        remote = record(writer="other",
                        rows={"water|sell": {"p": 19, "t": BASE, "r": 300}})
        merged = sync.merge_records(local, remote, BASE + 20)
        self.assertEqual(merged["rows"]["water|sell"]["p"], 21)

    def test_missing_rows_are_union(self):
        local = record(rows={"water|sell": {"p": 19, "t": BASE, "r": 300}})
        remote = record(writer="other",
                        rows={"scarf|buy": {"p": 22, "t": BASE + 1, "r": 300}})
        merged = sync.merge_records(local, remote, BASE + 20)
        self.assertEqual(set(merged["rows"]), {"water|sell", "scarf|buy"})

    def test_expired_rows_are_dropped(self):
        local = record(rows={"water|sell": {"p": 19, "t": BASE - 1000, "r": 60}})
        merged = sync.merge_records(local, None, BASE)
        self.assertIsNone(merged)

    def test_future_timestamps_are_clamped(self):
        far = BASE + 10_000
        remote = record(writer="other",
                        rows={"water|sell": {"p": 99, "t": far, "r": 300}})
        merged = sync.merge_records(None, remote, BASE)
        self.assertLessEqual(merged["rows"]["water|sell"]["t"],
                             BASE + sync.CLOCK_SKEW_LIMIT)

    def test_same_timestamp_tiebreak_is_deterministic(self):
        a = record(writer="aaa", rows={"water|sell": {"p": 10, "t": BASE, "r": 300}})
        b = record(writer="bbb", rows={"water|sell": {"p": 20, "t": BASE, "r": 300}})
        first = sync.merge_records(a, b, BASE)["rows"]["water|sell"]["p"]
        second = sync.merge_records(b, a, BASE)["rows"]["water|sell"]["p"]
        self.assertEqual(first, second)


class UploadTest(unittest.TestCase):
    def setUp(self):
        self.backend = sync.FakeBackend()
        self.local = LocalStore()
        self.engine = sync.SyncEngine(self.backend, "me", self.local.get,
                                      self.local.apply, now=lambda: BASE)

    def test_debounce_waits_before_upload(self):
        self.local.records["dour_4"] = record(t=BASE)
        self.engine.mark_dirty("dour_4")
        self.assertEqual(self.engine.upload_due(BASE + 1.0), [])      # 还没到防抖时间
        self.assertEqual(len(self.engine.upload_due(BASE + sync.UPLOAD_DEBOUNCE + 0.5)), 1)

    def test_upload_writes_the_object(self):
        self.local.records["dour_4"] = record(t=BASE)
        self.engine.mark_dirty("dour_4")
        self.engine.upload_due(BASE + sync.UPLOAD_DEBOUNCE + 0.5)
        self.assertIn("dour_4", self.backend.objects)
        self.assertEqual(self.backend.objects["dour_4"]["writer"], "me")

    def test_lost_response_is_treated_as_success(self):
        self.local.records["dour_4"] = record(t=BASE)
        self.engine.mark_dirty("dour_4")
        self.backend.fail_next_put = 1                 # 写成功但响应丢失
        self.assertEqual(self.engine.upload_due(BASE + sync.UPLOAD_DEBOUNCE + 0.5), ["dour_4"])
        self.assertEqual(self.engine.stats["errors"], 1)
        self.assertEqual(self.backend.objects["dour_4"]["writer"], "me")

    def test_conflict_merges_and_retries(self):
        self.local.records["dour_4"] = record(
            rows={"water|sell": {"p": 19, "t": BASE, "r": 300}})
        self.engine.mark_dirty("dour_4")
        # 别人先写了一份（同一个商人，但多了一行）
        self.backend.objects["dour_4"] = record(
            writer="other", rev=5,
            rows={"scarf|buy": {"p": 22, "t": BASE, "r": 300}})
        self.backend.etags["dour_4"] = '"x"'
        self.engine.upload_due(BASE + sync.UPLOAD_DEBOUNCE + 0.5)
        self.assertEqual(self.engine.stats["conflicts"], 1)
        rows = self.backend.objects["dour_4"]["rows"]
        self.assertEqual(set(rows), {"water|sell", "scarf|buy"})   # 两边都保住

    def test_rate_limit_backs_off(self):
        self.local.records["dour_4"] = record(t=BASE)
        self.engine.mark_dirty("dour_4")
        self.backend.rate_limited = 1
        self.assertEqual(self.engine.upload_due(BASE + sync.UPLOAD_DEBOUNCE + 0.5), [])
        self.assertGreater(self.engine._next_attempt, BASE + 3.0)

    def test_nothing_to_upload_when_expired(self):
        self.local.records["dour_4"] = record(
            rows={"water|sell": {"p": 19, "t": BASE - 1000, "r": 60}})
        self.engine.mark_dirty("dour_4")
        self.assertEqual(self.engine.upload_due(BASE + sync.UPLOAD_DEBOUNCE + 0.5), [])


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.backend = sync.FakeBackend()
        self.local = LocalStore()
        self.engine = sync.SyncEngine(self.backend, "me", self.local.get,
                                      self.local.apply, now=lambda: BASE)
        self.backend.objects["dour_4"] = record(
            writer="other", rows={"water|sell": {"p": 23, "t": BASE, "r": 300}})
        self.backend.etags["dour_4"] = '"1"'

    def test_poll_merges_remote_rows(self):
        self.engine.poll(BASE)
        self.assertEqual(self.local.records["dour_4"]["rows"]["water|sell"]["p"], 23)

    def test_second_poll_skips_unchanged(self):
        self.engine.poll(BASE)
        before = self.backend.get_calls
        self.engine.poll(BASE + 1)
        self.assertEqual(self.backend.get_calls, before)      # 没变就不下载

    def test_own_writes_are_skipped(self):
        self.backend.objects["kobi_1"] = record(
            merchant_id="kobi_1", writer="me",
            rows={"honey|sell": {"p": 12, "t": BASE, "r": 300}})
        self.backend.etags["kobi_1"] = '"2"'
        self.engine.poll(BASE)
        self.assertEqual(self.engine.stats["skipped_self"], 1)
        self.assertNotIn("kobi_1", self.local.records)

    def test_download_failure_keeps_local(self):
        self.local.records["dour_4"] = record(
            rows={"water|sell": {"p": 19, "t": BASE, "r": 300}})
        self.backend.fail_next_get = 1
        self.engine.poll(BASE)
        self.assertEqual(self.local.records["dour_4"]["rows"]["water|sell"]["p"], 19)
        self.assertGreaterEqual(self.engine.stats["errors"], 1)

    def test_duplicate_download_is_idempotent(self):
        self.engine.poll(BASE)
        first = dict(self.local.records["dour_4"]["rows"])
        self.backend.etags["dour_4"] = '"3"'          # 内容没变，etag 变了
        self.engine.poll(BASE + 1)
        self.assertEqual(self.local.records["dour_4"]["rows"], first)

    def test_expired_remote_is_ignored(self):
        self.backend.objects["ore_4"] = record(
            merchant_id="ore_4", writer="other",
            rows={"steel|sell": {"p": 13, "t": BASE - 1000, "r": 60}})
        self.backend.etags["ore_4"] = '"4"'
        self.engine.poll(BASE)
        self.assertNotIn("ore_4", self.local.records)


if __name__ == "__main__":
    unittest.main()

class SameRowsTest(unittest.TestCase):
    """t/r 每次观察都会变，但价格没变就不该重复上传（否则撞限流）。"""

    def _record(self, price, t, r):
        return {"rows": {"honey|sell": {"p": price, "t": t, "r": r}}}

    def test_same_price_with_different_timestamps_is_equal(self):
        from maplebot import sync
        self.assertTrue(sync.same_rows(self._record(13, 100.0, 50.0),
                                       self._record(13, 130.0, 20.0)))

    def test_price_change_is_different(self):
        from maplebot import sync
        self.assertFalse(sync.same_rows(self._record(13, 100.0, 50.0),
                                        self._record(19, 130.0, 20.0)))

