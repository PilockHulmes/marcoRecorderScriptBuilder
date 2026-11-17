"""共享功能的调度层：把 ledger、sync、活跃度和后端接起来。

线程模型：网络请求（几十毫秒到一两秒）**不能放在抓帧线程里**，否则会卡住识别。
所以这里自己起一个后台线程：

    每 0.5 秒醒一次 → 看该不该拉/该不该传 → 做完就睡

什么时候拉、拉多勤，由 :mod:`maplebot.activity` 的档位决定：

    T0 活跃 1 秒 / T1 跑图 3 秒 / T2 挂机 15 秒 / T3 离开 60 秒 / 关游戏不同步

什么时候传：本地记录变了（:meth:`ShareManager.mark_dirty`）→ 防抖 2 秒 → 传。
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from . import activity as activity_module
from . import logbook
from . import paths as paths_module
from . import share_config
from . import sync


def writer_id():
    """本机唯一 id：第一次启动时生成，之后固定（用来跳过自己写的回显）。"""
    path = paths_module.data_root() / "writer_id.txt"
    try:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
    except Exception:
        pass
    value = uuid.uuid4().hex
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value + "\n", encoding="utf-8")
    except Exception:
        pass
    return value


class ShareManager:
    """后台同步线程 + 对外接口（``mark_dirty`` / ``tick`` / ``stats``）。"""

    def __init__(self, ledger, backend=None, config=None, now=time.time):
        self.ledger = ledger
        self.now = now
        self.writer = writer_id()
        self.config = config if config is not None else share_config.load_config()
        self.backend = backend if backend is not None else self._make_backend()
        self.engine = (sync.SyncEngine(self.backend, self.writer,
                                       self._get_local, self._apply_remote, now=now)
                       if self.backend is not None else None)
        self.tier = activity_module.TIER_OFF
        self._next_poll = 0.0
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def _make_backend(self):
        # 用传进来的配置判断（测试会传空配置），不要回读磁盘上的 share.json
        if not (self.config.get("bucket") and self.config.get("token")):
            return None
        try:
            from .oss_backend import OssBackend
            return OssBackend(self.config)
        except Exception:
            return None

    @property
    def enabled(self):
        return self.engine is not None

    def _get_local(self, merchant_id):
        return self.ledger.merchant_record(merchant_id)

    def _apply_remote(self, merchant_id, record):
        self.ledger.apply_remote(merchant_id, record)

    # ------------------------------------------------------------------
    def set_tier(self, tier):
        """抓帧线程每帧告诉它"现在多活跃"。"""
        self.tier = tier

    def mark_dirty(self, merchant_id):
        if self.enabled and merchant_id:
            self.engine.mark_dirty(merchant_id)

    def tick(self, now=None):
        """按档位做一次拉取（上传由 mark_dirty + 防抖驱动）。"""
        if not self.enabled:
            return []
        now = self.now() if now is None else now
        interval = activity_module.Activity.poll_interval(self.tier)
        if interval is None:
            return []                     # 没开游戏：不同步
        if now < self._next_poll:
            return []
        self._next_poll = now + interval
        downloaded = self.engine.poll(now)
        if downloaded:
            # 拉到新数据：顺便把本地变了的也推上去（双向同步更快收敛）
            for merchant_id in downloaded:
                self.engine.mark_dirty(merchant_id)
        self.engine.upload_due(now)
        return downloaded

    def stats(self):
        if self.engine is None:
            return {}
        return dict(self.engine.stats)

    # ------------------------------------------------------------------
    def start(self):
        """起后台线程（重复调用无副作用）。"""
        if not self.enabled or self._thread is not None:
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="share-sync",
                                        daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None

    def _loop(self):
        failures = 0
        while not self._stop.is_set():
            try:
                self.tick()
                failures = 0
            except Exception as exc:
                # 以前是静默吞掉，线上出问题时完全查不到；现在记日志（限流，别刷爆）
                failures += 1
                if failures <= 3 or failures % 60 == 0:
                    logbook.log_event("共享異常", 次數=failures,
                                      類型=type(exc).__name__,
                                      訊息=str(exc)[:200])
            self._stop.wait(0.5)
