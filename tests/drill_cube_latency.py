"""测量两段延迟的真实值（不用 OCR 判断"变没变"，直接看像素）。

1. 点「重新設定」→ 确认框出现需要多久（检测绿色確認键的亮度）
2. 按空格 → 三条属性文字变成新值需要多久（比较文字区域哈希）

用法::

    .\\venv\\Scripts\\python.exe tests\\drill_cube_latency.py --trials 15
"""

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pydirectinput  # noqa: E402

from maplebot import cube, keys  # noqa: E402
from tests.drill_skill import focus, game_rect, grab  # noqa: E402

#: 確認按钮的位置（窗口内），对话框打开时这里是亮绿色
CONFIRM_BOX = (slice(486, 506), slice(605, 690))
CONFIRM_BRIGHT = 110


def dialog_open(frame):
    return frame[CONFIRM_BOX].mean() > CONFIRM_BRIGHT


def attr_signature(frame):
    parts = []
    for _badge, text in cube.row_boxes(frame):
        x, y, w, h = text
        crop = cv2.resize(frame[y:y + h, x:x + w], (24, 6), interpolation=cv2.INTER_AREA)
        parts.append(crop.astype(np.int16))
    return np.concatenate([p.ravel() for p in parts])


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=15)
    parser.add_argument("--cube", default="pink", choices=("pink", "cyan", "orange"))
    parser.add_argument("--poll", type=float, default=0.012)
    args = parser.parse_args(argv)

    from paddleocr import PaddleOCR
    import logging

    logging.getLogger("ppocr").setLevel(logging.ERROR)
    ocr = PaddleOCR(lang="ch", show_log=False)

    hwnd, window = game_rect()
    print("window", window, "| focus", focus(hwnd))
    time.sleep(0.5)

    keyboard = keys.Keyboard()
    frame = grab(window)
    if not cube.is_cube_selected(frame, ocr, args.cube):
        roller = cube.CubeRoller(grab=lambda: grab(window),
                                 click=lambda x, y: pydirectinput.click(window[0] + x, window[1] + y),
                                 key_api=keyboard, ocr=ocr, sleep=time.sleep, cube=args.cube)
        if not roller.select_cube():
            print("选不中目标方块")
            return 1
        print("已选中", args.cube)
        frame = grab(window)

    reset_x, reset_y = cube.box_center(frame, cube.RESET_BTN_BOX)
    dialog_times, render_times, timeouts = [], [], 0

    for index in range(args.trials):
        before = attr_signature(frame)
        pydirectinput.click(window[0] + reset_x, window[1] + reset_y)
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 1.0:
            if dialog_open(grab(window)):
                dialog_times.append((time.perf_counter() - t0) * 1000)
                break
            time.sleep(args.poll)
        else:
            print(f"第{index+1}次：等不到确认框")
            timeouts += 1
            continue

        keyboard.tap("space", hold=0.05)
        t1 = time.perf_counter()
        render = None
        while time.perf_counter() - t1 < 1.5:
            current = grab(window)
            if np.abs(attr_signature(current) - before).mean() > 2.0:
                render = (time.perf_counter() - t1) * 1000
                break
            time.sleep(args.poll)
        if render is None:
            print(f"第{index+1}次：属性没变（可能没洗成）")
            timeouts += 1
        else:
            render_times.append(render)
            frame = current
        time.sleep(0.15)

    def report(name, values):
        if not values:
            print(name, "无数据")
            return
        values = sorted(values)
        p50 = statistics.median(values)
        p95 = values[max(0, int(len(values) * 0.95) - 1)]
        print(f"{name}: p50={p50:.0f}ms p95={p95:.0f}ms max={values[-1]:.0f}ms n={len(values)}")

    report("确认框出现", dialog_times)
    report("属性刷新", render_times)
    print("失败/超时:", timeouts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
