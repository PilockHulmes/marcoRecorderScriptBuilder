"""扫大地图黄点（v3）：客户区坐标系，1:1 悬停。"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2
import numpy as np
import pydirectinput
import win32gui
import mss

# 画布区域（客户区坐标 = 截图坐标 - (1,32)）
MAP_REGION = (414, 118, 640, 505)
TIP_DX, TIP_DY, TIP_W, TIP_H = 25, 18, 330, 70
OUT_DIR = ROOT / "screenshots" / "trading" / "bigmap"


def find_game():
    best = None
    def callback(hwnd, _):
        nonlocal best
        if not win32gui.IsWindowVisible(hwnd) or win32gui.GetWindowText(hwnd) != "MapleStory":
            return
        r = win32gui.GetWindowRect(hwnd)
        area = (r[2] - r[0]) * (r[3] - r[1])
        if best is None or area > best[0]:
            best = (area, hwnd)
    win32gui.EnumWindows(callback, None)
    return best[1]


def find_dots(frame):
    x0, y0, w, h = MAP_REGION
    roi = frame[y0:y0 + h, x0:x0 + w]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([18, 150, 190]), np.array([38, 255, 255]))
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    dots = []
    for i in range(1, count):
        x, y, bw, bh, area = stats[i]
        if not (12 <= area <= 55):
            continue
        if not (5 <= bw <= 9 and 5 <= bh <= 9):
            continue
        if not (0.6 <= bw / bh <= 1.7):
            continue
        cx = int(round(centroids[i][0])) + x0
        cy = int(round(centroids[i][1])) + y0
        if all((cx - px) ** 2 + (cy - py) ** 2 > 25 for px, py in dots):
            dots.append((cx, cy))
    dots.sort(key=lambda p: (p[1] // 25, p[0]))
    return dots


def parse(lines):
    map_name = merchant = ""
    for line in lines:
        if "商人" in line:
            merchant = line.split("]")[-1].split("】")[-1].replace("商人", "").strip()
        if not map_name:
            for sep in ("：", ":"):
                if sep in line:
                    map_name = line.split(sep)[-1].strip()
                    break
    return map_name, merchant


def main():
    hwnd = find_game()
    print("foreground:", win32gui.GetForegroundWindow() == hwnd, flush=True)
    ox, oy = win32gui.ClientToScreen(hwnd, (0, 0))
    cw, ch = win32gui.GetClientRect(hwnd)[2:]
    print("client", (ox, oy), (cw, ch), flush=True)

    import logging
    from paddleocr import PaddleOCR

    logging.getLogger("ppocr").setLevel(logging.ERROR)
    ocr = PaddleOCR(lang="ch", show_log=False)

    def grab():
        with mss.mss() as sct:
            shot = sct.grab({"left": ox, "top": oy, "width": cw, "height": ch})
            return np.array(shot)[:, :, :3].copy()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dots = find_dots(grab())
    print("candidates", len(dots), flush=True)

    nodes = []
    for index, (px, py) in enumerate(dots, 1):
        pydirectinput.moveTo(ox + 1200, oy + 700)
        time.sleep(0.18)
        pydirectinput.moveTo(ox + px, oy + py)
        time.sleep(1.0)
        frame = grab()
        x0 = min(cw - 1, px + TIP_DX)
        y0 = min(ch - 1, py + TIP_DY)
        crop = frame[y0:y0 + TIP_H, x0:min(cw, x0 + TIP_W)]
        if crop.size == 0:
            continue
        image = OUT_DIR / f"v3_tip_{index:02d}.png"
        cv2.imwrite(str(image), crop)
        big = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        big = cv2.copyMakeBorder(big, 16, 16, 16, 16, cv2.BORDER_REPLICATE)
        result = ocr.ocr(big)
        lines = [str(item[1][0]) for item in result[0]] if result and result[0] else []
        map_name, merchant = parse(lines)
        nodes.append({"index": index, "x": px, "y": py, "map_name": map_name,
                      "merchant": merchant, "tooltip": " ".join(lines),
                      "tooltip_image": f"screenshots/trading/bigmap/{image.name}"})
        if map_name or merchant:
            print(f"{index:02d} ({px},{py}) {map_name!r} {merchant!r}", flush=True)

    out = ROOT / "data" / "trade" / "map_nodes.json"
    out.write_text(json.dumps({"version": 3, "coords": "client", "nodes": nodes},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    hit = sum(1 for n in nodes if n["map_name"] or n["merchant"])
    print("saved", out, "nodes", len(nodes), "hit", hit, flush=True)


if __name__ == "__main__":
    main()
