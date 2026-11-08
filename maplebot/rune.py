"""符文识图：截图裁剪 → DeepSeek 视觉 API → 4 个箭头方向。

只做一件事，不做任何时机/重试/寻路决策：

    frame ──find_panel()──> RunePanel(bbox, arrows)
          ──crop_panel()──> 放大后的 BGR 小图
          ──RuneSolver.solve()──> ["down", "down", "left", "down"]

为什么先本地定位再发图（而不是整屏发过去）：

- 整屏 1368×800 里箭头只有 ~28 px，缩放后更小，模型容易读错；
- 单图 token 有 1024 上限，所以"裁剪+放大"不额外花钱，却能把箭头占满画面；
- 本地定位同时给出 bbox，天然可用于"面板是否还在"的判断。

定位用的是颜色+形状，不用模型：箭头是红橙黄绿渐变（H≤75、S≥140、V≥150），
天空和大部分 UI 是蓝色（H≈100+），阈值分得很开。实测在 0.75×~2× 缩放、
±25 px 平移下都稳定，抹掉面板则 0 误报。
"""

import argparse
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import timing

DIRECTIONS = ("up", "down", "left", "right")

# ---------------------------------------------------------------- 定位参数
# 箭头一定出现在窗口中部偏上：横幅在 y≈21~24%，面板在 y≈28~38%
ROI_X0, ROI_X1 = 0.20, 0.75
ROI_Y0, ROI_Y1 = 0.25, 0.45

HUE_MAX = 75        # 红/橙/黄/绿；蓝色天空和 UI 在 90 以上
SAT_MIN = 140
VAL_MIN = 150

BASE_WIDTH = 1368.0   # 阈值按这个宽度标定，其它分辨率按比例缩放
AREA_MIN, AREA_MAX = 250, 3000
SIDE_MIN, SIDE_MAX = 15, 70
ROW_TOLERANCE = 25    # 同一行内允许的 y 偏差（px @1368）
ROW_SPREAD = 30       # 一行最多允许的总 y 跨度（px @1368）

# 裁剪/按键参数
PAD = 20              # 裁剪时四周留多少 px（@1368）
UPSCALE = 3.0         # 发给模型前放大倍数
HOLD = 0.03           # 每个方向键按住多久（秒）
INTERVAL = 0.10       # 两个方向键之间间隔（秒）
JITTER = 0.03         # 间隔抖动幅度（±秒），伪装成人手


@dataclass
class Blob:
    x: int
    y: int
    w: int
    h: int
    area: int
    cx: int
    cy: int


@dataclass
class RunePanel:
    """检测到的符文面板。

    :param bbox: 4 个箭头的并集 ``(x, y, w, h)``，窗口坐标。
    :param arrows: 4 个箭头 ``(x, y, w, h)``，已按从左到右排序。
    """

    bbox: tuple
    arrows: list = field(default_factory=list)

    def __len__(self):
        return len(self.arrows)


def _roi(width, height):
    return (
        int(width * ROI_X0),
        int(height * ROI_Y0),
        int(width * (ROI_X1 - ROI_X0)),
        int(height * (ROI_Y1 - ROI_Y0)),
    )


def _mask(work):
    hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0].astype(int)
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    mask = ((hue <= HUE_MAX) & (sat >= SAT_MIN) & (val >= VAL_MIN)).astype(np.uint8) * 255
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))


def find_blobs(frame):
    """在固定 ROI 内找"像箭头"的色块，返回窗口坐标下的 Blob 列表。"""
    height, width = frame.shape[:2]
    scale = width / BASE_WIDTH
    rx, ry, rw, rh = _roi(width, height)
    work = frame[ry:ry + rh, rx:rx + rw]
    if work.size == 0:
        return []

    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(_mask(work), 8)
    blobs = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if not (AREA_MIN * scale * scale <= area <= AREA_MAX * scale * scale):
            continue
        if not (SIDE_MIN * scale <= w <= SIDE_MAX * scale):
            continue
        if not (SIDE_MIN * scale <= h <= SIDE_MAX * scale):
            continue
        blobs.append(
            Blob(
                x=int(x + rx), y=int(y + ry), w=int(w), h=int(h), area=int(area),
                cx=int(centroids[i][0] + rx), cy=int(centroids[i][1] + ry),
            )
        )
    return blobs


def _rows(blobs, tolerance):
    """按 y 把色块聚成若干行。"""
    rows = []
    for blob in sorted(blobs, key=lambda b: b.cy):
        for row in rows:
            if abs(row[-1].cy - blob.cy) <= tolerance:
                row.append(blob)
                break
        else:
            rows.append([blob])
    return rows


def find_panel(frame):
    """找符文面板；没找到返回 None。

    判定条件：存在某一行**恰好 4 个**色块，且这一行的 y 跨度不超过阈值。
    多行都满足时取面积和最大的那行（符文箭头通常比背景杂色更"实"）。
    """
    height, width = frame.shape[:2]
    scale = width / BASE_WIDTH
    blobs = find_blobs(frame)
    if not blobs:
        return None

    candidates = []
    for row in _rows(blobs, ROW_TOLERANCE * scale):
        if len(row) != 4:
            continue
        if max(b.cy for b in row) - min(b.cy for b in row) > ROW_SPREAD * scale:
            continue
        candidates.append(row)
    if not candidates:
        return None

    row = max(candidates, key=lambda r: sum(b.area for b in r))
    row.sort(key=lambda b: b.cx)
    x0 = min(b.x for b in row)
    y0 = min(b.y for b in row)
    x1 = max(b.x + b.w for b in row)
    y1 = max(b.y + b.h for b in row)
    return RunePanel(bbox=(x0, y0, x1 - x0, y1 - y0), arrows=[(b.x, b.y, b.w, b.h) for b in row])


def crop_panel(frame, panel, padding=PAD, upscale=UPSCALE):
    """按 bbox 裁出箭头区域（含 padding），并放大。

    padding 会按窗口宽度缩放，边缘自动收敛，不会越界。
    """
    height, width = frame.shape[:2]
    scale = width / BASE_WIDTH
    pad = int(round(padding * scale))
    x, y, w, h = panel.bbox
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(width, x + w + pad)
    y1 = min(height, y + h + pad)
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        raise ValueError("裁剪区域为空")
    if upscale and upscale != 1:
        crop = cv2.resize(crop, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    return crop


def _default_key_api():
    import pydirectinput

    return pydirectinput


def press_directions(directions, key_api=None, sleep=None, hold=HOLD, interval=INTERVAL, jitter=JITTER):
    """按顺序把方向键敲进去（默认 100ms 间隔 + ±30ms 抖动）。

    每按一个键之前都会调用 :func:`maplebot.stop.check`，所以急停时不会卡在序列中间。
    """
    from . import stop

    for direction in directions:
        if direction not in DIRECTIONS:
            raise ValueError(f"非法方向：{direction!r}")
    api = key_api if key_api is not None else _default_key_api()
    wait = sleep if sleep is not None else timing.sleep_precise
    for index, direction in enumerate(directions):
        stop.check()
        api.keyDown(direction)
        wait(hold)
        api.keyUp(direction)
        if index < len(directions) - 1:
            wait(max(0.0, interval + random.uniform(-jitter, jitter)))


def _main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m maplebot.rune",
        description="离线验证：读一张截图 → 定位符文面板 → 裁剪 → 调 DeepSeek 读出 4 个方向。",
    )
    parser.add_argument("image", nargs="?", default=str(Path(__file__).resolve().parents[1] / "rune_example.png"))
    parser.add_argument("--save-crop", metavar="PATH", help="把实际发给模型的图存下来")
    parser.add_argument("--no-api", action="store_true", help="只做定位与裁剪，不调 API")
    args = parser.parse_args(argv)

    path = Path(args.image)
    if not path.is_file():
        print(f"找不到图片：{path}", file=sys.stderr)
        return 2
    frame = cv2.imread(str(path))
    if frame is None:
        print(f"图片读不出来：{path}", file=sys.stderr)
        return 2

    panel = find_panel(frame)
    if panel is None:
        print("没检测到符文面板（4 个箭头）")
        return 1
    print(f"面板 bbox={panel.bbox}  箭头={panel.arrows}")
    crop = crop_panel(frame, panel)
    print(f"裁剪后尺寸={crop.shape[1]}x{crop.shape[0]}")
    if args.save_crop:
        cv2.imwrite(args.save_crop, crop)
        print(f"已保存：{args.save_crop}")
    if args.no_api:
        return 0

    from .rune_api import RuneAPIError, RuneConfigError, RuneSolver

    try:
        solver = RuneSolver()
        directions = solver.solve(crop)
    except (RuneConfigError, RuneAPIError) as exc:
        print(f"解符文失败：{exc}", file=sys.stderr)
        return 3
    print(f"方向（左→右）：{directions}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
