"""测量洗魔方的"冷却"：洗完一次后要等多久才能再点开确认框。

用法::

    .\\venv\\Scripts\\python.exe tests\\drill_cube_cooldown.py
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pydirectinput  # noqa: E402

from maplebot import cube, keys  # noqa: E402
from tests.drill_skill import focus, game_rect, grab  # noqa: E402
from tests.drill_cube_latency import dialog_open  # noqa: E402

GAPS = (0.20, 0.50, 0.80, 1.10, 1.40)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=3, help="每个间隔试几次")
    parser.add_argument("--cube", default="pink", choices=("pink", "cyan", "orange"))
    args = parser.parse_args(argv)

    from paddleocr import PaddleOCR
    import logging

    logging.getLogger("ppocr").setLevel(logging.ERROR)
    ocr = PaddleOCR(lang="ch", show_log=False)

    hwnd, window = game_rect()
    print("focus", focus(hwnd))
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
    frame = grab(window)
    x, y = cube.box_center(frame, cube.RESET_BTN_BOX)

    for gap in GAPS:
        ok = 0
        for _ in range(args.trials):
            time.sleep(gap)                      # 洗完到下一次点击之间等 gap
            pydirectinput.click(window[0] + x, window[1] + y)
            deadline = time.perf_counter() + 1.0
            opened = False
            while time.perf_counter() < deadline:
                if dialog_open(grab(window)):
                    opened = True
                    break
                time.sleep(0.012)
            if opened:
                ok += 1
                keyboard.tap("space", hold=0.05)   # 关掉对话框并洗
                time.sleep(0.5)
            else:
                time.sleep(0.4)
        print(f"间隔 {gap:.2f}s -> 确认框出现 {ok}/{args.trials}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
