"""跑商大地图：找地图点 + 推道路邻接。

用法::

    python -m maplebot.trade_map screenshots/trading/地图.png
    python -m maplebot.trade_map <img> --save data/trade/map_graph.json
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "screenshots" / "trading" / "big_map" / "点带白色角.png"
DEFAULT_REGION = (0.0, 0.0, 1.0, 1.0)      # 相对整图，调用方一般传画布区域
DOT_THRESHOLD = 0.90
NMS_DISTANCE = 7


def imread_unicode(path):
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def load_template(path=TEMPLATE_PATH, shrink=1):
    """读点的模板，返回 (彩色模板, 圆形掩膜)。四角是道路背景，必须用掩膜排除。"""
    tpl = imread_unicode(path)
    if tpl is None:
        raise FileNotFoundError(f"模板读取失败：{path}")
    h, w = tpl.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    cv2.circle(mask, (w // 2, h // 2), max(2, min(h, w) // 2 - shrink), 255, -1)
    return tpl, mask


def find_dots(frame, template=None, mask=None, region=DEFAULT_REGION,
              threshold=DOT_THRESHOLD, max_points=120):
    """用带掩膜的模板匹配找地图点，按分数贪心去重，返回 [(x, y, score)]。"""
    if frame is None or frame.size == 0:
        return []
    if template is None:
        template, mask = load_template()
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = region
    rx0, ry0 = int(x0 * w), int(y0 * h)
    roi = frame[ry0:int(y1 * h), rx0:int(x1 * w)]
    th, tw = template.shape[:2]
    if roi.shape[0] < th or roi.shape[1] < tw:
        return []
    result = cv2.matchTemplate(roi, template, cv2.TM_CCORR_NORMED, mask=mask)
    ys, xs = np.where(result >= threshold)
    if len(xs) == 0:
        return []
    scores = result[ys, xs]
    order = np.argsort(-scores)[: max_points * 40]
    kept = []
    for idx in order:
        score = float(scores[idx])
        cx, cy = int(xs[idx]) + tw // 2, int(ys[idx]) + th // 2
        if any(abs(cx - kx) < NMS_DISTANCE and abs(cy - ky) < NMS_DISTANCE for kx, ky, _ in kept):
            continue
        kept.append((cx, cy, score))
        if len(kept) >= max_points:
            break
    kept.sort(key=lambda p: (p[1], p[0]))
    return [(px + rx0, py + ry0, s) for px, py, s in kept]


def road_mask(frame, v_min=185, s_max=70):
    """道路掩膜：路是浅米白（亮、低饱和），沙地更黄更饱和。"""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 2] >= v_min) & (hsv[:, :, 1] <= s_max)).astype(np.uint8) * 255
    kernel = np.ones((3, 3), np.uint8)
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)


def _is_road(mask, x, y):
    h, w = mask.shape[:2]
    if not (0 <= x < w and 0 <= y < h):
        return False
    return mask[int(y), int(x)] > 0


def build_graph(points, mask, max_dist=170, road_ratio=0.9):
    """两点间连线上"路面像素"占比够高就认为相邻；穿过第三个点的连线丢弃。"""
    edges = []
    n = len(points)
    for i in range(n):
        for j in range(i + 1, n):
            ax, ay = points[i][0], points[i][1]
            bx, by = points[j][0], points[j][1]
            dist = float(np.hypot(bx - ax, by - ay))
            if dist > max_dist or dist < 8:
                continue
            steps = int(dist) + 1
            hits = 0
            for k in range(1, steps):
                t = k / steps
                if _is_road(mask, ax + (bx - ax) * t, ay + (by - ay) * t):
                    hits += 1
            ratio = hits / max(1, steps - 1)
            if ratio < road_ratio:
                continue
            blocked = False
            for m in range(n):
                if m in (i, j):
                    continue
                px, py = points[m][0], points[m][1]
                if np.hypot(px - ax, py - ay) < 10 or np.hypot(px - bx, py - by) < 10:
                    continue
                t = ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / (dist * dist)
                if 0.15 < t < 0.85:
                    if np.hypot(px - (ax + (bx - ax) * t), py - (ay + (by - ay) * t)) < 9:
                        blocked = True
                        break
            if blocked:
                continue
            edges.append({"a": i, "b": j, "pixels": round(dist, 1), "road": round(ratio, 3)})
    return edges


def analyse(frame, region=DEFAULT_REGION, dot_threshold=DOT_THRESHOLD):
    template, mask = load_template()
    dots = find_dots(frame, template, mask, region=region, threshold=dot_threshold)
    roads = road_mask(frame)
    edges = build_graph(dots, roads)
    return {"dots": [{"id": f"n{i+1:02d}", "x": x, "y": y, "score": round(s, 3)}
                     for i, (x, y, s) in enumerate(dots)],
            "edges": edges}


def _main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="解析跑商大地图：点 + 道路邻接")
    parser.add_argument("image")
    parser.add_argument("--save", help="输出 JSON 路径")
    parser.add_argument("--region", default="0,0,1,1", help="画布区域 x0,y0,x1,y1（比例）")
    parser.add_argument("--threshold", type=float, default=DOT_THRESHOLD)
    args = parser.parse_args(argv)

    frame = imread_unicode(args.image)
    if frame is None:
        print("读图失败", args.image)
        return 1
    region = tuple(float(v) for v in args.region.split(","))
    data = analyse(frame, region=region, dot_threshold=args.threshold)
    print(json.dumps({"dots": len(data["dots"]), "edges": len(data["edges"])}, ensure_ascii=False))
    for dot in data["dots"][:5]:
        print("  dot", dot)
    for edge in data["edges"][:5]:
        print("  edge", edge)
    if args.save:
        out = Path(args.save)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("saved", out)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
