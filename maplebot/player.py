"""在小地图上找自己（黄点 + 白圈），并做时序跟踪。

为什么不像原来那样直接用灰度模板匹配：

- 小地图上的图标是"白圈 + 彩色填充"：自己是**黄**、其他玩家是**红**、
  NPC/传送点是**绿**、符文是紫色菱形。灰度模板会把"白圈"当成主要特征，
  绿点/红点都可能过阈值；
- 实测（`rune_icon.png` 的小地图）：玩家黄点 HSV=(28,255,254)，
  平台是 (5,221,53)~(12,245,76)，亮度差一个量级 → 用颜色门控非常干净，
  整个小地图里只有 1 个黄色块。

所以这里用「黄点 + 白圈」做候选检测，再用**连续性**在多候选时做选择，
并处理遮挡（保留上一帧、标记 stale）和抖动（一阶低通）。
"""

import time
from dataclasses import dataclass

import cv2
import numpy as np

from . import minimap

# 黄色门控（实测 28,255,254；平台/地形亮度远低于 200）
YELLOW_HUE = (18, 42)
YELLOW_S_MIN = 190
YELLOW_V_MIN = 190

# 黄块尺寸（小地图上的图标是固定像素大小，不随地图大小变）
AREA_MIN, AREA_MAX = 6, 200
SIDE_MIN, SIDE_MAX = 3, 16

# 白圈：以黄块中心为圆心，半径 2.8~5.2 的环上要有足够多"亮"像素。
# 实测（rune_icon）：玩家 0.32，平台/绿点/菱形/空地 全是 0.00，所以门槛放 0.20 很安全。
RING_INNER, RING_OUTER = 2.8, 5.2
RING_V_MIN = 170
RING_S_MAX = 90
RING_RATIO_MIN = 0.12

# 跟踪参数
GATE_FRAC = 0.10        # 连续两帧之间允许的位移（占小地图宽度）
STALE_SECONDS = 0.35    # 超过这么久没看到，就认为"位置未知"
SMOOTHING = 0.65        # 一阶低通系数：新测量占多少


@dataclass(frozen=True)
class PlayerCandidate:
    """小地图上检测到的一个"黄点+白圈"候选。"""

    x: int          # 中心，帧坐标
    y: int
    w: int
    h: int
    score: float    # 0~1，白圈占比与尺寸合理度的组合
    ring: float     # 白圈占比

    def as_tuple(self):
        return self.x, self.y, self.w, self.h


def _ring_ratio(hsv, cx, cy, inner=RING_INNER, outer=RING_OUTER):
    """以 (CX,CY) 为圆心，半径 [INNER,OUTER) 的环上"亮且不饱和"像素的占比。

    用饱和度把"白圈"和"黄块本身"分开：黄块 S≈255，白圈 S≈8。
    """
    height, width = hsv.shape[:2]
    reach = int(np.ceil(outer)) + 1
    x0, x1 = max(0, cx - reach), min(width, cx + reach + 1)
    y0, y1 = max(0, cy - reach), min(height, cy + reach + 1)
    patch = hsv[y0:y1, x0:x1]
    if patch.size == 0:
        return 0.0
    yy, xx = np.ogrid[y0 - cy:y1 - cy, x0 - cx:x1 - cx]
    dist = np.sqrt(xx * xx + yy * yy)
    annulus = (dist >= inner) & (dist < outer)
    if not annulus.any():
        return 0.0
    bright = (patch[:, :, 2] >= RING_V_MIN) & (patch[:, :, 1] <= RING_S_MAX)
    return float(bright[annulus].mean())


def _content_rect(frame, content=None):
    """把参数统一成内容区 ``(x, y, w, h)``；None 时自动找小地图并去掉白框。"""
    if content is not None:
        if hasattr(content, "as_tuple"):
            content = content.as_tuple()
        return tuple(int(v) for v in content)
    box = minimap.find_minimap(frame)
    if box is None:
        return None
    return box.inner().as_tuple()


def find_candidates(frame, content=None):
    """返回内容区里所有"黄点+白圈"候选（按分数降序）。

    :param content: 小地图**内容区** ``(x, y, w, h)``（不含白框）。
                    不传就自动找小地图。
    """
    if frame is None or getattr(frame, "size", 0) == 0:
        return []
    rect = _content_rect(frame, content)
    if rect is None:
        return []
    x0, y0, cw, ch = rect
    crop = frame[y0:y0 + ch, x0:x0 + cw]
    if crop.size == 0:
        return []

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(
        hsv,
        np.array([YELLOW_HUE[0], YELLOW_S_MIN, YELLOW_V_MIN]),
        np.array([YELLOW_HUE[1], 255, 255]),
    )
    if not mask.any():
        return []
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    candidates = []
    for i in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[i])
        if not (AREA_MIN <= area <= AREA_MAX):
            continue
        if not (SIDE_MIN <= w <= SIDE_MAX) or not (SIDE_MIN <= h <= SIDE_MAX):
            continue
        cx, cy = int(round(centroids[i][0])), int(round(centroids[i][1]))
        ring = _ring_ratio(hsv, cx, cy)
        if ring < RING_RATIO_MIN:
            continue
        area_score = 1.0 - abs(area - 24) / 24.0      # 24 px² 最典型
        area_score = max(0.0, min(1.0, area_score))
        score = 0.7 * ring + 0.3 * area_score
        candidates.append(
            PlayerCandidate(
                x=x0 + cx,
                y=y0 + cy,
                w=w,
                h=h,
                score=round(float(score), 3),
                ring=round(float(ring), 3),
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def find_player(frame, content=None):
    """返回分数最高的候选（没有则 None）。多候选时的取舍交给 :class:`PlayerTracker`。"""
    candidates = find_candidates(frame, content)
    return candidates[0] if candidates else None


class PlayerTracker:
    """把逐帧的候选串成一条平滑的位置轨迹。

    - 有多个候选时，选离"上一帧位置 + 速度×dt"最近的那个；
    - 一帧没看到 → 保留上一帧位置，标记 ``stale``（**不会**像旧代码那样归零）；
    - 超过 ``stale_seconds`` 没看到 → ``position`` 变成 None，调用方就不该依赖位置做动作。
    """

    def __init__(self, gate_frac=GATE_FRAC, stale_seconds=STALE_SECONDS,
                 smoothing=SMOOTHING, clock=time.monotonic):
        self.gate_frac = float(gate_frac)
        self.stale_seconds = float(stale_seconds)
        self.smoothing = float(smoothing)
        self._clock = clock
        self.position = None          # (x, y) 平滑后的位置
        self.velocity = (0.0, 0.0)    # 像素/秒
        self.raw = None               # 最近一次原始观测
        self.last_seen = None         # 时间戳
        self.jumps = 0                # 位移过大的次数（切图/复活）
        self.misses = 0               # 连续没看到候选的帧数

    # ------------------------------------------------------------ 状态
    @property
    def stale(self):
        if self.last_seen is None or self.position is None:
            return True
        return (self._clock() - self.last_seen) > self.stale_seconds

    def age(self):
        if self.last_seen is None:
            return float("inf")
        return self._clock() - self.last_seen

    # ------------------------------------------------------------ 更新
    def update(self, frame, content=None, now=None):
        """喂一帧；返回平滑后的位置 ``(x, y)`` 或 None（位置未知）。

        :param content: 小地图内容区 ``(x, y, w, h)``；不传就自动找小地图。
        """
        now = self._clock() if now is None else float(now)
        rect = _content_rect(frame, content)
        candidates = find_candidates(frame, rect) if rect is not None else []

        if not candidates:
            self.misses += 1
            if self.stale:
                self.position = None
            return self.position

        self.misses = 0
        gate_px = self.gate_frac * max(1, rect[2])
        chosen, jumped = self._choose(candidates, now, gate_px)

        if self.position is None or jumped:
            # 首次捕获，或者明显是切图/复活：直接对齐，不做平滑
            self.position = (float(chosen.x), float(chosen.y))
            self.velocity = (0.0, 0.0)
        else:
            dt = max(1e-3, now - self.last_seen) if self.last_seen is not None else 0.0
            predicted = (
                self.position[0] + self.velocity[0] * dt,
                self.position[1] + self.velocity[1] * dt,
            )
            alpha = self.smoothing
            new_pos = (
                alpha * chosen.x + (1 - alpha) * predicted[0],
                alpha * chosen.y + (1 - alpha) * predicted[1],
            )
            if dt > 0:
                self.velocity = (
                    (new_pos[0] - self.position[0]) / dt,
                    (new_pos[1] - self.position[1]) / dt,
                )
            self.position = new_pos

        self.raw = chosen
        self.last_seen = now
        return self.position

    def _choose(self, candidates, now, gate_px):
        """多候选时选最符合连续性（预测位置）的那个；返回 (候选, 是否跳变)。"""
        if self.position is None:
            return candidates[0], False

        dt = max(0.0, now - self.last_seen) if self.last_seen is not None else 0.0
        predicted = (
            self.position[0] + self.velocity[0] * dt,
            self.position[1] + self.velocity[1] * dt,
        )
        best = min(
            candidates,
            key=lambda c: (c.x - predicted[0]) ** 2 + (c.y - predicted[1]) ** 2,
        )
        distance = float(np.hypot(best.x - predicted[0], best.y - predicted[1]))
        if distance > gate_px:
            # 跳得太远：切图 / 复活 / 重新捕获，直接对齐而不是慢慢平滑
            self.jumps += 1
            return best, True
        return best, False

    def reset(self):
        self.position = None
        self.velocity = (0.0, 0.0)
        self.raw = None
        self.last_seen = None
        self.misses = 0
