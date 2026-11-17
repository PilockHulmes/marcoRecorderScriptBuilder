import unittest

from maplebot import activity, share, sync


BASE = 1_800_000_000.0


class FakeLedger:
    """只实现共享需要的两个方法。"""

    def __init__(self):
        self.records = {}
        self.applied = []

    def merchant_record(self, merchant_id):
        return self.records.get(merchant_id)

    def apply_remote(self, merchant_id, record):
        self.applied.append((merchant_id, record))


def record(merchant_id="dour_4", price=19, t=BASE, r=300.0, writer="other"):
    return sync.make_record(merchant_id, "孤獨的沙漠-1", writer, 1,
                            {"water|sell": {"p": price, "t": t, "r": r}})


class ShareManagerTest(unittest.TestCase):
    def make(self, tier=activity.TIER_ACTIVE):
        backend = sync.FakeBackend()
        ledger = FakeLedger()
        manager = share.ShareManager(ledger, backend=backend,
                                     config={"bucket": "b", "token": "t"},
                                     now=lambda: BASE)
        manager.set_tier(tier)
        manager.writer = "me"
        manager.engine.writer = "me"
        return manager, backend, ledger

    def test_thread_not_started_when_disabled(self):
        manager = share.ShareManager(FakeLedger(), backend=None,
                                     config={}, now=lambda: BASE)
        self.assertFalse(manager.enabled)
        self.assertFalse(manager.start())
        self.assertEqual(manager.tick(BASE), [])

    def test_poll_interval_follows_activity_tier(self):
        manager, backend, ledger = self.make(activity.TIER_ACTIVE)
        backend.objects["dour_4"] = record()
        backend.etags["dour_4"] = '"1"'
        manager.tick(BASE)                       # 第一次拉
        self.assertEqual(len(ledger.applied), 1)
        backend.objects["kobi_1"] = record("kobi_1", price=12)
        backend.etags["kobi_1"] = '"2"'
        manager.tick(BASE + 0.5)                 # T0：1 秒未到，不拉
        self.assertEqual(len(ledger.applied), 1)
        manager.tick(BASE + 1.2)                 # 到点了
        self.assertEqual(len(ledger.applied), 2)

    def test_idle_tier_polls_slowly(self):
        manager, backend, ledger = self.make(activity.TIER_IDLE)
        backend.objects["dour_4"] = record()
        backend.etags["dour_4"] = '"1"'
        manager.tick(BASE)
        backend.objects["kobi_1"] = record("kobi_1", price=12)
        backend.etags["kobi_1"] = '"2"'
        manager.tick(BASE + 5)                   # T2：15 秒一次
        self.assertEqual(len(ledger.applied), 1)
        manager.tick(BASE + 16)
        self.assertEqual(len(ledger.applied), 2)

    def test_no_game_means_no_sync(self):
        manager, backend, ledger = self.make(activity.TIER_OFF)
        backend.objects["dour_4"] = record()
        backend.etags["dour_4"] = '"1"'
        self.assertEqual(manager.tick(BASE), [])
        self.assertEqual(ledger.applied, [])

    def test_dirty_upload_happens_through_engine(self):
        manager, backend, ledger = self.make()
        ledger.records["dour_4"] = record(writer="me")      # 本地的记录
        manager.mark_dirty("dour_4")
        manager.tick(BASE)                                    # 防抖未到
        self.assertNotIn("dour_4", backend.objects)
        manager.tick(BASE + 3)                                # 防抖过了
        self.assertIn("dour_4", backend.objects)

    def test_writer_id_is_stable(self):
        first = share.writer_id()
        second = share.writer_id()
        self.assertEqual(first, second)
        self.assertGreaterEqual(len(first), 8)


if __name__ == "__main__":
    unittest.main()
