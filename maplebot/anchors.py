"""用界面上的固定锚点，测出"当前画面的缩放比和界面原点"。

为什么需要：游戏在不同分辨率下会把界面整体放大（1920 下是 1366 的 1.4056 倍），
但有人会用"大画布 + 1366 原始尺寸界面"（带鱼屏跑 1920x1080），
这时按 `宽/1366` 算缩放就完全错了。所以要从画面里**测**出来。

锚点选的是商店/货舱面板标题栏里的 `SHOP` `CARGO` 字样：黄字、深底、位置固定。
两个锚点的**间距**是主要信息：1366 下相差 277 像素，放大后按比例变宽。

```
间距 277 → 尺度 1.000（界面 1:1）
间距 389 → 尺度 1.404（1920 原生）
```

搜索是"多尺度模板匹配"，只在面板可能出现的中部区域找，并且只在小地图打开时
标定一次（约 0.2~0.4 秒），之后靠缓存。
"""

from __future__ import annotations

import cv2
import numpy as np

from . import paths as paths_module

#: 标题栏条带在 1366 界面里的位置（同时含 SHOP 和 CARGO 字样）
STRIP_BOX = (505, 170, 335, 26)

#: SHOP / CARGO 字样相对条带左上角的偏移（1366 基准）
SHOP_IN_STRIP = (10, 3)
CARGO_IN_STRIP = (287, 5)

#: 两个锚点在 1366 界面里的水平间距（保留给"间距验证"用）
BASE_GAP = CARGO_IN_STRIP[0] - SHOP_IN_STRIP[0]

#: 搜索尺度范围（覆盖 1366 原始到 2 倍）
SCALE_MIN = 0.90
SCALE_MAX = 1.90
SCALE_STEP = 0.05

#: 命中分数下限：低于这个值就当没找到（避免把别的地方当成标题）
SCORE_MIN = 0.70

_cache = {}


def load_patches():
    """读取锚点模板；没有就返回空字典。"""
    if "patches" in _cache:
        return _cache["patches"]
    table = {}
    folder = paths_module.trade_dir() / "anchors"
    for key, name in (("strip", "title_strip.png"),
                      ("shop", "shop_title.png"), ("cargo", "cargo_title.png")):
        path = folder / name
        if not path.exists():
            continue
        data = np.fromfile(str(path), dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if image is not None:
            table[key] = image
    _cache["patches"] = table
    return table


def search(frame, patch, region=None, lo=SCALE_MIN, hi=SCALE_MAX, step=SCALE_STEP):
    """多尺度搜索一个锚点，返回 ``(score, scale, (x, y))``；找不到返回 None。"""
    if frame is None or patch is None or patch.size == 0:
        return None
    x0, y0, w, h = region if region else (0, 0, frame.shape[1], frame.shape[0])
    area = frame[y0:y0 + h, x0:x0 + w]
    if area.size == 0:
        return None
    best = None
    for scale in np.arange(lo, hi + 1e-9, step):
        width = int(round(patch.shape[1] * scale))
        height = int(round(patch.shape[0] * scale))
        if width < 8 or height < 6 or width >= area.shape[1] or height >= area.shape[0]:
            continue
        template = cv2.resize(patch, (width, height), interpolation=cv2.INTER_AREA)
        result = cv2.matchTemplate(area, template, cv2.TM_CCOEFF_NORMED)
        _min, maximum, _loc, position = cv2.minMaxLoc(result)
        if best is None or maximum > best[0]:
            best = (float(maximum), float(round(scale, 3)),
                    (position[0] + x0, position[1] + y0))
    return best


def _back_to_full(hit, factor, frame, patch):
    """把半分辨率的结果换算回原图，并在附近用原图精修一次。"""
    if hit is None:
        return None
    score, scale, (x, y) = hit
    full_scale = scale / factor
    x = int(round(x / factor))
    y = int(round(y / factor))
    region = (max(0, x - 20), max(0, y - 20), 90, 70)
    refined = search(frame, patch, region=region,
                     lo=max(0.5, full_scale * 0.94), hi=full_scale * 1.06, step=0.01)
    if refined is not None and refined[0] >= score * 0.9:
        return refined
    return (score, full_scale, (x, y))


def middle_region(frame, ratio=0.55):
    """面板一般出现在画面中部：只搜中间这块，快 2~3 倍。"""
    height, width = frame.shape[:2]
    w = int(width * ratio)
    h = int(height * ratio)
    return ((width - w) // 2, (height - h) // 2, w, h)


def calibrate(frame, use_region=True):
    """测出当前画面的尺度和两个锚点位置。

    锚点用**整条标题栏**（同时含 SHOP 和 CARGO 字样）：
    一条 335x26 的条带内容很独特，不会像"两个小锚点各自取最高分"那样
    在错误尺度上凑巧凑出一对。

    返回 ``{"scale": float, "shop": (x,y), "cargo": (x,y), "score": float}``。
    """
    patches = load_patches()
    strip = patches.get("strip")
    if strip is None:
        return {"scale": None, "shop": None, "cargo": None, "score": 0.0}

    factor = 0.5
    small = cv2.resize(frame, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    regions = ([middle_region(small)] if use_region else []) + [None]

    best = None
    for region in regions:
        x0, y0, w, h = region if region else (0, 0, small.shape[1], small.shape[0])
        area = small[y0:y0 + h, x0:x0 + w]
        for scale in np.arange(SCALE_MIN * factor, SCALE_MAX * factor + 1e-9,
                               SCALE_STEP * factor):
            template = cv2.resize(
                strip,
                (max(8, int(round(strip.shape[1] * scale))),
                 max(8, int(round(strip.shape[0] * scale)))),
                interpolation=cv2.INTER_AREA)
            if template.shape[0] >= area.shape[0] or template.shape[1] >= area.shape[1]:
                continue
            result = cv2.matchTemplate(area, template, cv2.TM_CCOEFF_NORMED)
            _min, maximum, _loc, position = cv2.minMaxLoc(result)
            if maximum < SCORE_MIN:
                continue
            candidate = (float(maximum), scale / factor,
                         (position[0] + x0, position[1] + y0))
            if best is None or candidate[0] > best[0]:
                best = candidate
        # 只有非常确定的命中才提前收工；否则继续搜全屏，取更好的那个
        if best is not None and best[0] >= 0.94:
            break

    if best is None:
        return {"scale": None, "shop": None, "cargo": None, "score": 0.0}

    score, coarse_scale, coarse_pos = best
    # 回到原图，用更细的步长精修一次
    refined = search(frame, strip,
                     region=(max(0, int(coarse_pos[0] / factor) - 12),
                             max(0, int(coarse_pos[1] / factor) - 12),
                             int(strip.shape[1] / factor) + 40,
                             int(strip.shape[0] / factor) + 40),
                     lo=max(SCALE_MIN, coarse_scale * 0.96),
                     hi=min(SCALE_MAX, coarse_scale * 1.04), step=0.005)
    if refined is not None and refined[0] >= score * 0.95:
        score, scale, position = refined
    else:
        scale, position = coarse_scale, (coarse_pos[0] / factor,
                                         coarse_pos[1] / factor)

    shop = (position[0] + SHOP_IN_STRIP[0] * scale,
            position[1] + SHOP_IN_STRIP[1] * scale)
    cargo = (position[0] + CARGO_IN_STRIP[0] * scale,
             position[1] + CARGO_IN_STRIP[1] * scale)
    return {"scale": float(round(scale, 4)), "shop": shop, "cargo": cargo,
            "score": float(score)}


def view_scale(frame_scale):
    """把标定结果翻译成"该怎么读这一帧"。"""
    if frame_scale is None:
        return "resize"
    if abs(frame_scale - 1.0) <= 0.02:
        return "native"          # 界面 1:1：平移对齐即可，不用缩放
    return "resize"              # 其他尺度：缩回 1366 再读


def shift_to_canonical(frame, shop_position):
    """把画面平移，让商店面板回到 1366 界面里的位置（界面 1:1 时用）。"""
    if shop_position is None:
        return frame
    dx = int(round(SHOP_IN_STRIP[0])) + STRIP_BOX[0] - int(shop_position[0])
    dy = int(round(SHOP_IN_STRIP[1])) + STRIP_BOX[1] - int(shop_position[1])
    if dx == 0 and dy == 0:
        return frame
    height, width = frame.shape[:2]
    matrix = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(frame, matrix, (width, height), flags=cv2.INTER_NEAREST,
                          borderMode=cv2.BORDER_REPLICATE)
