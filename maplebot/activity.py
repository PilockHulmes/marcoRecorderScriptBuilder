"""判断玩家现在有多活跃，用来决定共享数据多久拉一次。

为什么要这个：在线共享是"按请求量花钱"的，挂机的人如果也每秒拉一次，
钱就白花了。这里用几路本地信号估一个活跃档位：

    1. 系统输入空闲（鼠标/键盘最后动过多久）—— 最直接
    2. 游戏窗口在不在（没开游戏就不该同步）
    3. 角色有没有动（小地图上的黄点位置变化）
    4. 有没有过图 / 开商店

档位：

    T0 活跃   商店/货舱开着，或 2 分钟内有输入/移动   → 1 秒
    T1 跑图   5 分钟内动过，游戏在前台               → 3 秒
    T2 挂机   5~15 分钟没动                          → 15 秒
    T3 离开   输入空闲超过 15 分钟                    → 60 秒
    OFF       没开游戏                               → 不同步

注意 ``GetLastInputInfo`` 读的是**整个系统**的空闲时间：在游戏里挂着、
但在浏览器里打字，会被判成活跃。这是刻意放宽的——宁可多花一点，也不要
把真在玩的人降频。
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

#: 档位
TIER_OFF = -1
TIER_ACTIVE = 0
TIER_RUNNING = 1
TIER_IDLE = 2
TIER_AWAY = 3

#: 各档位对应的轮询间隔（秒）
POLL_INTERVAL = {
    TIER_ACTIVE: 1.0,
    TIER_RUNNING: 3.0,
    TIER_IDLE: 15.0,
    TIER_AWAY: 60.0,
}

#: 判定阈值（秒）
ACTIVE_IDLE = 120.0        # 2 分钟内有输入 -> 活跃
RUNNING_IDLE = 300.0       # 5 分钟内 -> 跑图档
AWAY_IDLE = 900.0          # 15 分钟 -> 离开

#: 角色移动判定：小地图上的位置变化超过这个比例算"动了"
MOVE_EPSILON = 0.02


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def system_idle_seconds():
    """系统空闲秒数（鼠标/键盘最后活动到现在的间隔）。失败返回 0。"""
    try:
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        elapsed_ms = ctypes.windll.kernel32.GetTickCount() - info.dwTime
        return max(0.0, min(float(elapsed_ms) / 1000.0, 86400.0))
    except Exception:
        return 0.0


class Activity:
    """维护"最近一次活跃是什么时候"，并给出当前档位和轮询间隔。"""

    def __init__(self, get_idle=None):
        #: 可注入的空闲时间来源（测试用）
        self._get_idle = get_idle or system_idle_seconds
        self._last_active = None      # monotonic，最近一次"有动作"的时刻
        self._last_move = None        # monotonic，最近一次角色移动
        self._last_position = None

    def update(self, now, game_running=True, shop_open=False, position=None,
               map_changed=False):
        """喂一帧的信号，返回当前档位。``now`` 用 ``time.monotonic()``。"""
        if not game_running:
            return TIER_OFF

        moved = False
        if position is not None and self._last_position is not None:
            dx = abs(position[0] - self._last_position[0])
            dy = abs(position[1] - self._last_position[1])
            moved = (dx + dy) >= MOVE_EPSILON
        if position is not None:
            self._last_position = tuple(position)
        if moved:
            self._last_move = now

        if map_changed:
            self._last_move = now          # 过图也是"动过"
        idle = float(self._get_idle())
        if shop_open or map_changed or moved:
            self._last_active = now
        elif idle <= ACTIVE_IDLE:
            self._last_active = now

        since_move = None if self._last_move is None else (now - self._last_move)
        if shop_open or map_changed:
            return TIER_ACTIVE
        if idle <= ACTIVE_IDLE:
            return TIER_ACTIVE
        if since_move is not None and since_move <= ACTIVE_IDLE:
            return TIER_ACTIVE          # 最近两分钟走过路
        if idle <= RUNNING_IDLE:
            return TIER_RUNNING
        if since_move is not None and since_move <= RUNNING_IDLE:
            return TIER_RUNNING
        if idle <= AWAY_IDLE:
            return TIER_IDLE
        return TIER_AWAY

    @staticmethod
    def poll_interval(tier):
        """该档位多久拉一次（秒）；关游戏时返回 None（不同步）。"""
        return POLL_INTERVAL.get(tier)
