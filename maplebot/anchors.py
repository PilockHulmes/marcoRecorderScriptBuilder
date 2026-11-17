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

#: 锚点模板在 1366 界面里的位置（裁图时用的坐标，仅作说明）
SHOP_PATCH_BOX = (515, 173, 40, 18)
CARGO_PATCH_BOX = (792, 175, 45, 16)

#: 两个锚点在 1366 界面里的水平间距
BASE_GAP = CARGO_PATCH_BOX[0] - SHOP_PATCH_BOX[0]

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
    for key, name in (("shop", "shop_title.png"), ("cargo", "cargo_title.png")):
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

    返回 ``{"scale": float, "shop": (x,y), "cargo": (x,y), "score": float}``；
    两个锚点都找不到时返回 ``{"scale": None, ...}``。
    """
    patches = load_patches()
    if "shop" not in patches or "cargo" not in patches:
        return {"scale": None, "shop": None, "cargo": None, "score": 0.0}

    # 先在半分辨率上粗搜（快 4 倍），再回到原图局部精修
    factor = 0.5
    small = cv2.resize(frame, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    region = middle_region(small) if use_region else None
    shop_small = search(small, patches["shop"], region=region,
                        lo=SCALE_MIN * factor, hi=SCALE_MAX * factor,
                        step=SCALE_STEP * factor)
    cargo_small = search(small, patches["cargo"], region=region,
                         lo=SCALE_MIN * factor, hi=SCALE_MAX * factor,
                         step=SCALE_STEP * factor)
    shop = _back_to_full(shop_small, factor, frame, patches["shop"])
    cargo = _back_to_full(cargo_small, factor, frame, patches["cargo"])
    if shop is None or cargo is None or shop[0] < SCORE_MIN or cargo[0] < SCORE_MIN:
        return {"scale": None, "shop": None, "cargo": None,
                "score": min(shop[0] if shop else 0.0, cargo[0] if cargo else 0.0)}

    # 两个锚点的间距最可靠：比模板尺度网格的 5% 步长精确得多
    gap = cargo[2][0] - shop[2][0]
    scale = gap / float(BASE_GAP) if BASE_GAP else 1.0
    if not (SCALE_MIN - 0.1 <= scale <= SCALE_MAX + 0.2):
        return {"scale": None, "shop": None, "cargo": None,
                "score": min(shop[0], cargo[0])}

    # 用这个尺度把两个锚点再对一次（尺度变了，模板尺寸也要变）
    shop2 = search(frame, patches["shop"], region=(max(0, shop[2][0] - 12),
                                                   max(0, shop[2][1] - 12), 60, 50),
                   lo=scale * 0.97, hi=scale * 1.03, step=0.01)
    cargo2 = search(frame, patches["cargo"], region=(max(0, cargo[2][0] - 12),
                                                     max(0, cargo[2][1] - 12), 70, 50),
                    lo=scale * 0.97, hi=scale * 1.03, step=0.01)
    shop_pos = shop2[2] if shop2 else shop[2]
    cargo_pos = cargo2[2] if cargo2 else cargo[2]
    return {"scale": float(round(scale, 4)), "shop": shop_pos, "cargo": cargo_pos,
            "score": float(min(shop[0], cargo[0]))}


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
    dx = SHOP_PATCH_BOX[0] - int(shop_position[0])
    dy = SHOP_PATCH_BOX[1] - int(shop_position[1])
    if dx == 0 and dy == 0:
        return frame
    height, width = frame.shape[:2]
    matrix = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(frame, matrix, (width, height), flags=cv2.INTER_NEAREST,
                          borderMode=cv2.BORDER_REPLICATE)
