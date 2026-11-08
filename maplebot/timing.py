"""精确等待：既不烧 CPU，也不丢精度。

背景
----
`commandBuilderLib.delay()` 原来是纯自旋（``while perf_counter() < end: pass``）：
等 200 ms 就烧 200 ms CPU。而脚本大部分时间都在「等」（落地、后摇、点击间隔），
于是进程长期占满一个核，与游戏和截屏线程抢 CPU。

做法
----
把一次等待拆成两段：

1. 先用 ``time.sleep()`` 睡到「还差 tail 毫秒」；
2. 最后 ``tail`` 毫秒自旋，保证返回值不早于 deadline（精度和纯自旋一致）。

``tail`` 在模块导入时用几次 ``time.sleep(4ms)`` 实测过冲量来定：Windows 的定时器粒度
可能是 1 ms 也可能是 15.6 ms（取决于有没有进程调过 ``timeBeginPeriod``），粒度粗的机器
会自动得到更大的 tail，从而把误差吃在自旋里。tail 被限制在 2~20 ms。

如果「剩余时间 − tail」比定时器粒度还短（例如 15 ms 的点击间隔），就不再睡眠、直接自旋：
比粒度还短的 ``sleep`` 必然过冲，睡反而更不准。

想恢复老行为（纯自旋、最准、最费 CPU）：
``set MAPLEBOT_PRECISE_DELAY=1``（Windows PowerShell: ``$env:MAPLEBOT_PRECISE_DELAY=1``）。
"""

import os
import time

#: 自旋尾段的上下限（秒）
TAIL_MIN = 0.002
TAIL_MAX = 0.020

#: 睡眠时长低于这个值就不睡了，直接自旋——比定时器粒度还短的 sleep 只会带来过冲
MIN_SLEEP = 0.005

#: 是否强制纯自旋（老行为）
PRECISE = os.environ.get("MAPLEBOT_PRECISE_DELAY", "").strip().lower() in {"1", "true", "yes", "on"}


def _measure_tail():
    """实测 ``time.sleep`` 的过冲量，据此决定自旋尾段长度。"""
    if PRECISE:
        return 0.0
    overshoot = 0.0
    for _ in range(3):
        t0 = time.perf_counter()
        time.sleep(0.004)
        overshoot = max(overshoot, time.perf_counter() - t0 - 0.004)
    return min(TAIL_MAX, max(TAIL_MIN, overshoot + 0.001))


#: 自旋尾段长度（秒）；0 表示纯自旋
TAIL = _measure_tail()


def tail():
    """当前使用的自旋尾段（秒），0 表示纯自旋。测试/诊断用。"""
    return TAIL


def sleep_precise(seconds):
    """等待 SECONDS 秒。

    - 不早于 deadline 返回（尾段自旋保证）；
    - 长等待时 CPU 接近 0（只有最后 tail 毫秒在自旋）；
    - ``seconds <= 0`` 直接返回。
    """
    seconds = float(seconds)
    if seconds <= 0:
        return

    deadline = time.perf_counter() + seconds
    if TAIL <= 0:
        while time.perf_counter() < deadline:
            pass
        return

    remain = deadline - time.perf_counter()
    # 睡眠时长太短就不睡：比定时器粒度还短的 sleep 必然过冲，反而不准
    if remain > TAIL + MIN_SLEEP:
        time.sleep(remain - TAIL)
    while time.perf_counter() < deadline:
        pass


__all__ = ["TAIL", "PRECISE", "sleep_precise", "tail"]
