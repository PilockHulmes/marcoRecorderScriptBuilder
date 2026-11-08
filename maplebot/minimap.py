"""小地图定位：找那个「白色（半透明）圆角边框」。

客户端改版后，原来靠两张角模板（`minimap_tl/br_template.png`）定位的方式失效了：
新 UI 的小地图是**一块深色面板里的地图区，外面套一圈白色圆角边框**。

两条现实约束决定了做法：

1. **尺寸不固定**：小地图随地图大小变化，宽、高、宽高比都不固定 → 不能写死尺寸，
   只能"量出左上/右下两个角"；筛选条件放宽到 0.8~6.0 的宽高比、窗口的 6%~40%。
2. **边框是半透明的**：颜色随背后的游戏画面漂移（实测同一次截图里也有 228/186/177 等
   不同亮度），所以**不能用一个固定白色阈值**。做法是：
   - 用一组由严到宽的阈值依次尝试（V≥210、185、160、135、110，S≤40~95）；
   - 真正决定"这是不是小地图"的不是绝对白，而是**局部对比**：
     边框那一圈比它**外侧 3px 的环**明显更亮（面板底色是暗的）；
   - 四边各自允许有缺口（半透明/被遮挡），只要每边 ≥30%、整圈 ≥55%。

实测：1368×800 上 0.6 ms 定位到 (8, 99, 198, 82)；合成样本里，地图内部亮度 30~220、
边框透明度 0.4~1.0、尺寸 140×55~400×90 全部命中。

这个模块以后还会放「小地图上的符文菱形」检测，所以单独成文件。
"""

from dataclasses import dataclass

import cv2
import numpy as np

# 由严到宽的白阈值梯度：(V 下限, S 上限)
THRESHOLDS = ((210, 40), (185, 50), (160, 65), (135, 80), (110, 95))

# 只在窗口左上角找，避免命中其它 UI
ROI_X0, ROI_Y0, ROI_X1, ROI_Y1 = 0.0, 0.0, 0.35, 0.40

# 尺寸门槛（按窗口宽高比例）：小地图可能很小也可能很大，但不会是缩略图大小
MIN_W_FRAC, MIN_H_FRAC = 0.06, 0.04
MAX_W_FRAC, MAX_H_FRAC = 0.40, 0.40
RATIO_MIN, RATIO_MAX = 0.8, 6.0

# 边框连续性：每条边至少这么多比例是白的，整圈平均至少这么多
SIDE_MIN = 0.30
TOTAL_MIN = 0.55
EDGE_BAND = 2

# 局部对比：边框要比外侧环亮这么多；边框本身也不能太暗
BORDER_V_MIN = 80
CONTRAST_MIN = 20
OUTER_PAD = 3

# 白框本身有厚度，真正的地图内容要往里缩一点
DEFAULT_INSET = 3


@dataclass(frozen=True)
class MinimapBox:
    """小地图白框的外接矩形（窗口坐标）——也就是左上、右下两个角。"""

    x: int
    y: int
    w: int
    h: int

    @property
    def right(self):
        return self.x + self.w

    @property
    def bottom(self):
        return self.y + self.h

    @property
    def center(self):
        return self.x + self.w // 2, self.y + self.h // 2

    def inner(self, inset=DEFAULT_INSET):
        """去掉白框厚度后的地图内容区。"""
        inset = max(0, int(inset))
        return MinimapBox(
            self.x + inset,
            self.y + inset,
            max(1, self.w - 2 * inset),
            max(1, self.h - 2 * inset),
        )

    def as_tuple(self):
        return self.x, self.y, self.w, self.h

    def contains(self, px, py):
        return self.x <= px < self.right and self.y <= py < self.bottom


def _mask_at(hsv, v_min, s_max):
    return cv2.inRange(
        hsv,
        np.array([0, 0, v_min]),
        np.array([180, s_max, 255]),
    )


def _row_coverage(mask, y, x0, x1):
    row = mask[y, x0:x1]
    return float((row > 0).mean()) if row.size else 0.0


def _col_coverage(mask, x, y0, y1):
    col = mask[y0:y1, x]
    return float((col > 0).mean()) if col.size else 0.0


def _side_coverages(mask, x, y, w, h, band=EDGE_BAND):
    """四条边各自的白色覆盖率。

    取 EDGE_BAND 行/列的**最大值**：UI 缩放后半透明白框只有 1~1.5 px，
    抗锯齿会让某一行漏掉像素。
    """
    height, width = mask.shape[:2]
    rows = [min(height - 1, y + k) for k in range(band)]
    bottom_rows = [max(0, y + h - 1 - k) for k in range(band)]
    cols = [min(width - 1, x + k) for k in range(band)]
    right_cols = [max(0, x + w - 1 - k) for k in range(band)]

    top = max(_row_coverage(mask, r, x, x + w) for r in rows)
    bottom = max(_row_coverage(mask, r, x, x + w) for r in bottom_rows)
    left = max(_col_coverage(mask, c, y, y + h) for c in cols)
    right = max(_col_coverage(mask, c, y, y + h) for c in right_cols)
    return float(top), float(bottom), float(left), float(right)


def _ring_mean(v_channel, x, y, w, h, pad=OUTER_PAD):
    """边框**外侧**一圈的平均亮度（面板底色通常比边框暗很多）。"""
    height, width = v_channel.shape[:2]
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(width, x + w + pad), min(height, y + h + pad)
    outer = np.zeros(v_channel.shape, np.uint8)
    outer[y0:y1, x0:x1] = 1
    outer[y:y + h, x:x + w] = 0
    values = v_channel[outer.astype(bool)]
    return float(values.mean()) if values.size else 0.0


def _candidate_ok(mask, v_channel, box, width, height, roi_w=None, roi_h=None):
    """检查一个候选框是不是"白框 + 暗外侧"的小地图。"""
    x, y, w, h = box.x, box.y, box.w, box.h
    if w < max(24, int(width * MIN_W_FRAC)) or h < max(20, int(height * MIN_H_FRAC)):
        return None
    if w > width * MAX_W_FRAC or h > height * MAX_H_FRAC:
        return None
    # 占满整个搜索区 → 没有"外侧"可比，不是小地图
    if roi_w and roi_h and (w >= roi_w * 0.95 or h >= roi_h * 0.95):
        return None
    ratio = w / h
    if not (RATIO_MIN <= ratio <= RATIO_MAX):
        return None

    sides = _side_coverages(mask, x, y, w, h)
    if min(sides) < SIDE_MIN:
        return None
    total = sum(sides) / 4.0
    if total < TOTAL_MIN:
        return None

    border_v = float(v_channel[y:y + EDGE_BAND, x:x + w].mean())
    if border_v < BORDER_V_MIN:
        return None
    outer_v = _ring_mean(v_channel, x, y, w, h)
    if border_v - outer_v < CONTRAST_MIN:
        return None

    # 纯色亮块（内部和边框一样亮、且毫无纹理）不是地图
    inner = v_channel[y + 4:y + h - 4, x + 4:x + w - 4]
    if inner.size:
        inner_v = float(inner.mean())
        inner_std = float(inner.std())
        if inner_v >= border_v - 5 and inner_std < 3:
            return None

    return {
        "ratio": ratio,
        "sides": sides,
        "total": total,
        "border_v": border_v,
        "outer_v": outer_v,
    }


def find_minimap(frame, roi=None, debug=False):
    """在 FRAME 左上角找小地图白框，返回 :class:`MinimapBox` 或 None。

    :param roi: 可选搜索区域 ``(x, y, w, h)``；默认按 :data:`ROI_*`。
    :param debug: 为真时返回 ``(box, info)``，info 含命中的阈值、四边覆盖率、对比度等。
    """
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    height, width = frame.shape[:2]

    if roi is None:
        rx = int(width * ROI_X0)
        ry = int(height * ROI_Y0)
        rw = int(width * (ROI_X1 - ROI_X0))
        rh = int(height * (ROI_Y1 - ROI_Y0))
    else:
        rx, ry, rw, rh = (int(v) for v in roi)
    rx, ry = max(0, rx), max(0, ry)
    rw, rh = min(rw, width - rx), min(rh, height - ry)
    if rw <= 0 or rh <= 0:
        return None

    work = frame[ry:ry + rh, rx:rx + rw]
    hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
    v_channel = hsv[:, :, 2]

    for v_min, s_max in THRESHOLDS:
        mask = _mask_at(hsv, v_min, s_max)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        for contour in contours:
            bx, by, bw, bh = cv2.boundingRect(contour)
            box = MinimapBox(bx + rx, by + ry, bw, bh)
            local = MinimapBox(bx, by, bw, bh)
            info = _candidate_ok(mask, v_channel, local, width, height, roi_w=rw, roi_h=rh)
            if info is None:
                continue
            score = bw * bh
            if best is None or score > best[0]:
                best = (score, box, dict(info, threshold=(v_min, s_max), score=score))
        if best is not None:
            return (best[1], best[2]) if debug else best[1]

    return (None, None) if debug else None


def _main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m maplebot.minimap",
        description="离线验证：在截图里定位小地图的白框（左上/右下两个角）。",
    )
    parser.add_argument("image", nargs="?", default="rune_example.png")
    parser.add_argument("--save", metavar="PATH", help="把定位结果画到图上另存")
    args = parser.parse_args(argv)

    frame = cv2.imread(args.image)
    if frame is None:
        print(f"图片读不出来：{args.image}")
        return 2
    box, info = find_minimap(frame, debug=True)
    if box is None:
        print("没找到小地图白框")
        return 1
    print(f"白框: x={box.x} y={box.y} w={box.w} h={box.h}  内容区={box.inner().as_tuple()}")
    print(
        f"  阈值={info['threshold']} 四边覆盖率={[round(s, 2) for s in info['sides']]} "
        f"整体={info['total']:.2f} 宽高比={info['ratio']:.2f} "
        f"边框亮度={info['border_v']:.0f} 外侧={info['outer_v']:.0f}"
    )
    if args.save:
        vis = frame.copy()
        cv2.rectangle(vis, (box.x, box.y), (box.right, box.bottom), (0, 0, 255), 1)
        inner = box.inner()
        cv2.rectangle(vis, (inner.x, inner.y), (inner.right, inner.bottom), (0, 255, 0), 1)
        cv2.imwrite(args.save, vis)
        print(f"已保存：{args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
