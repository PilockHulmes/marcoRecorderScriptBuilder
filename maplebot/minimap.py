"""小地图定位：找那个「白色圆角边框」的矩形。

客户端改版后，原来靠两张角模板（`minimap_tl/br_template.png`）定位的方式失效了：
新 UI 的小地图是一块深色地图区，外面套一圈 2 px 的浅灰白（实测 BGR ≈ 228）圆角边框，
再外面才是面板标题栏。所以改成直接找这个白框：

    near-white mask → 连通域 → 要求「四条边大部分是白的」且「内部是暗的」

实测：在 1368×800 的截图上 0.6 ms 定位到 (8, 99, 198, 82)；
0.75×/1.5× 缩放、整体平移都能稳定找到；没有白框时返回 None（该模块随后回退到旧模板）。

这个模块以后还会放「小地图上的符文菱形」检测，所以单独成文件。
"""

from dataclasses import dataclass

import cv2
import numpy as np

# 白框的判定阈值（实测边框 BGR=(228,228,228) → HSV 的 V=228、S=0）
WHITE_V_MIN = 170
WHITE_S_MAX = 45

# 只在窗口左上角找，避免命中其它 UI
ROI_X0, ROI_Y0, ROI_X1, ROI_Y1 = 0.0, 0.0, 0.30, 0.35

# 尺寸门槛（按窗口宽高比例，兼容不同分辨率）
MIN_W_FRAC, MIN_H_FRAC = 0.04, 0.025
MAX_W_FRAC, MAX_H_FRAC = 0.40, 0.40
RATIO_MIN, RATIO_MAX = 1.3, 5.5

# 四条边至少这么大比例是白的；内部平均亮度不能太高（地图背景是暗的）
EDGE_MIN = 0.70
EDGE_BAND = 2
INNER_V_MAX = 150

# 白框本身有厚度，真正的地图内容要往里缩一点
DEFAULT_INSET = 3


@dataclass(frozen=True)
class MinimapBox:
    """小地图白框的外接矩形（窗口坐标）。"""

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


def _white_mask(image):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    return cv2.inRange(
        hsv,
        np.array([0, 0, WHITE_V_MIN]),
        np.array([180, WHITE_S_MAX, 255]),
    )


def _row_coverage(mask, y, x0, x1):
    row = mask[y, x0:x1]
    return float((row > 0).mean()) if row.size else 0.0


def _col_coverage(mask, x, y0, y1):
    col = mask[y0:y1, x]
    return float((col > 0).mean()) if col.size else 0.0


def _edge_coverage(mask, x, y, w, h, band=EDGE_BAND):
    """返回 (上, 下, 左, 右) 四条边白色像素的占比。

    取 EDGE_BAND 行/列的**最大值**而不是单行：UI 缩放后白框只有 1~1.5 px，
    抗锯齿会让某一行漏掉像素，单行采样会误判成"边框不连续"。
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


def find_minimap(frame, roi=None, debug=False):
    """在 FRAME 左上角找白色圆角边框，返回 :class:`MinimapBox` 或 None。

    :param roi: 可选的搜索区域 ``(x, y, w, h)``；默认按 :data:`ROI_*` 取左上角。
    :param debug: 为真时返回 ``(box, info)``，info 里有各边覆盖率、宽高比、内部亮度。
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
    mask = _white_mask(work)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    min_w = max(12, int(width * MIN_W_FRAC))
    min_h = max(10, int(height * MIN_H_FRAC))
    max_w = int(width * MAX_W_FRAC)
    max_h = int(height * MAX_H_FRAC)

    best = None
    best_info = None
    for contour in contours:
        bx, by, bw, bh = cv2.boundingRect(contour)
        if bw < min_w or bh < min_h or bw > max_w or bh > max_h:
            continue
        ratio = bw / bh
        if not (RATIO_MIN <= ratio <= RATIO_MAX):
            continue

        edges = _edge_coverage(mask, bx, by, bw, bh)
        if min(edges) < EDGE_MIN:
            continue

        inner = work[by + 5:by + bh - 5, bx + 5:bx + bw - 5]
        if inner.size == 0:
            continue
        inner_v = float(cv2.cvtColor(inner, cv2.COLOR_BGR2HSV)[:, :, 2].mean())
        if inner_v > INNER_V_MAX:
            continue

        score = bw * bh
        if best is None or score > best[0]:
            best = (score, MinimapBox(bx + rx, by + ry, bw, bh))
            best_info = {
                "edges": edges,
                "ratio": ratio,
                "inner_v": inner_v,
                "score": score,
            }

    if best is None:
        return (None, None) if debug else None
    return (best[1], best_info) if debug else best[1]


def _main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m maplebot.minimap",
        description="离线验证：在截图里定位小地图的白色圆角边框。",
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
    print(f"  四边白色占比={[round(e, 2) for e in info['edges']]}  宽高比={info['ratio']:.2f}  内部亮度={info['inner_v']:.0f}")
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
