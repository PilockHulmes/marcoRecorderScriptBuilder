"""标定洗魔方的最短间隔：点按钮后等多久、按空格后等多久才读属性。

判据：每次洗完三条属性应该变化。连续两次文本完全相同 → 大概率这次没洗成功
（或者读得太早）。用这个"重复率"衡量速度是否安全。

用法::

    .\\venv\\Scripts\\python.exe tests\\drill_cube_speed.py --cube pink --rolls 4
"""

import argparse
import itertools
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pydirectinput  # noqa: E402

from maplebot import cube, keys  # noqa: E402
from tests.drill_skill import focus, game_rect, grab  # noqa: E402

DIALOG_WAITS = (0.10, 0.20, 0.35)
CONFIRM_WAITS = (0.15, 0.25, 0.35, 0.50)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cube", default="pink", choices=("pink", "cyan", "orange"))
    parser.add_argument("--rolls", type=int, default=4, help="每组试几次")
    args = parser.parse_args(argv)

    from paddleocr import PaddleOCR
    import logging

    logging.getLogger("ppocr").setLevel(logging.ERROR)
    ocr = PaddleOCR(lang="ch", show_log=False)

    hwnd, window = game_rect()
    print("window", window, "| focus", focus(hwnd))
    time.sleep(0.5)

    def click_xy(x, y):
        pydirectinput.click(window[0] + x, window[1] + y)

    keyboard = keys.Keyboard()
    roller = cube.CubeRoller(
        grab=lambda: grab(window),
        click=click_xy,
        key_api=keyboard,
        ocr=ocr,
        sleep=time.sleep,
        cube=args.cube,
        guard=lambda: __import__("win32gui").GetForegroundWindow() == hwnd,
    )

    frame = grab(window)
    if not cube.is_cube_selected(frame, ocr, args.cube):
        if not roller.select_cube():
            print("选不中目标方块，退出")
            return 1
        print("已选中", args.cube)

    height, width = frame.shape[:2]
    slot_y = int(cube.SLOT_Y * height)

    rows = []
    for dialog_wait, confirm_wait in itertools.product(DIALOG_WAITS, CONFIRM_WAITS):
        same = 0
        previous = None
        for _ in range(args.rolls):
            click_xy(*cube.box_center(frame, cube.RESET_BTN_BOX))
            time.sleep(dialog_wait)
            keyboard.tap(roller.roll_key, hold=0.05)
            time.sleep(confirm_wait)
            lines = cube.read_lines(grab(window), ocr=ocr)
            texts = [line.raw for line in lines]
            if previous is not None and texts == previous:
                same += 1
            previous = texts
            time.sleep(0.15)
        rate = same / max(1, args.rolls - 1)
        rows.append((dialog_wait, confirm_wait, same, args.rolls - 1, rate))
        print(f"dialog={dialog_wait:.2f} confirm={confirm_wait:.2f} -> 重复 {same}/{args.rolls-1} ({rate:.0%})")

    out = ROOT / "detections" / "cube_speed.csv"
    out.parent.mkdir(exist_ok=True)
    out.write_text("dialog,confirm,same,total,rate\n"
                   + "".join(f"{a},{b},{c},{d},{e:.3f}\n" for a, b, c, d, e in rows),
                   encoding="utf-8")
    print("结果写入", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
