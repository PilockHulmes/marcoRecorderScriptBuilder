"""真实洗一次魔方（消耗 1 个粉色魔方 = 800,000 楓幣）。

先切焦点到游戏，然后：选中粉色魔方 → 点「重新設定」→ Enter 确认
→ 等 0.85s → 读三行属性 → 判定。

用法::

    .\\venv\\Scripts\\python.exe tests\\drill_cube.py            # 洗一次
    .\\venv\\Scripts\\python.exe tests\\drill_cube.py --dry    # 只看能否选中，不洗
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


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true", help="只检查选中状态，不洗")
    parser.add_argument("--main", default="LUK")
    parser.add_argument("--key", default="enter", help="确认键：enter 或 space")
    parser.add_argument("--rolls", type=int, default=1, help="最多洗几次")
    parser.add_argument("--cube", default="pink", choices=("pink", "cyan", "orange"),
                        help="用哪种方块洗")
    args = parser.parse_args(argv)

    print("管理员权限:", keys.is_elevated())
    hwnd, window = game_rect()
    print("窗口:", window, "| 切焦点:", focus(hwnd))
    time.sleep(0.5)

    frame = grab(window)
    header_ocr = None
    if args.dry:
        from paddleocr import PaddleOCR as _P
        import logging as _l
        _l.getLogger("ppocr").setLevel(_l.ERROR)
        header_ocr = _P(lang="ch", show_log=False)
        print("标题:", cube.read_header(frame, header_ocr))
        print("当前方块:", args.cube, "已选中:", cube.is_cube_selected(frame, header_ocr, args.cube))
        return 0

    from paddleocr import PaddleOCR
    import logging

    logging.getLogger("ppocr").setLevel(logging.ERROR)

    roller = cube.CubeRoller(
        grab=lambda: grab(window),
        click=lambda x, y: pydirectinput.click(window[0] + x, window[1] + y),
        key_api=keys.Keyboard(),
        ocr=PaddleOCR(lang="ch", show_log=False),
        sleep=time.sleep,
        main=args.main,
        roll_key=args.key,
        cube=args.cube,
        guard=lambda: __import__("win32gui").GetForegroundWindow() == hwnd,
    )

    shots = ROOT / "screenshots" / "cube_rolls"
    shots.mkdir(parents=True, exist_ok=True)
    import cv2

    import csv

    log_path = shots / "rolls_log.csv"
    new_log = not log_path.exists()
    log_file = log_path.open("a", newline="", encoding="utf-8")
    writer = csv.writer(log_file)
    if new_log:
        writer.writerow(["index", "time", "image", "keep", "reason", "line1", "line2", "line3"])

    keep = False
    reason = ""
    for index in range(1, args.rolls + 1):
        try:
            lines = roller.roll_once()
        except cube.RollError as exc:
            print("中止:", exc)
            break
        stamp = time.strftime("%Y%m%d_%H%M%S")
        image = shots / f"roll_{index:02d}_{stamp}.png"
        cv2.imwrite(str(image), grab(window))
        keep, reason = cube.judge(lines, main=args.main)
        print(f"第 {index} 次 [{image.name}] keep={keep} ({reason})")
        for line in lines:
            print(f"    {line.grade}  {line.raw!r:34} -> {line.stat:5s} {line.kind:9s} {line.value}")
        writer.writerow([index, stamp, image.name, int(keep), reason] + [line.raw for line in lines])
        log_file.flush()
        if keep:
            roller._keys.tap("esc", hold=0.04)
            roller._sleep(0.4)
            print("满足条件，已按 Esc 退出洗魔方界面")
            break
    log_file.close()
    print("总计:", roller.rolls, "次; 保留:", keep, reason)
    print("日志:", log_path)
    return 0 if keep else 0


if __name__ == "__main__":
    sys.exit(main())
