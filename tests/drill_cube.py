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
    args = parser.parse_args(argv)

    print("管理员权限:", keys.is_elevated())
    hwnd, window = game_rect()
    print("窗口:", window, "| 切焦点:", focus(hwnd))
    time.sleep(0.5)

    frame = grab(window)
    print("粉色魔方已选中:", cube.is_selected(frame),
          "| 青色像素:", cube.cyan_pixels(frame, cube.PINK_CUBE_BOX))
    if args.dry:
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
    )

    frame_before = grab(window)
    lines = roller.roll_once()
    print("洗出结果:")
    for line in lines:
        print(f"  {line.grade}  {line.raw!r:28} -> stat={line.stat:5s} "
              f"kind={line.kind:9s} value={line.value}")
    shots = ROOT / "screenshots" / "cube_rolls"
    shots.mkdir(parents=True, exist_ok=True)
    import cv2
    cv2.imwrite(str(shots / f"roll_{time.strftime('%Y%m%d_%H%M%S')}.png"), grab(window))
    keep, reason = cube.judge(lines, main=args.main)
    print("判定:", keep, reason)
    return 0 if keep else 0


if __name__ == "__main__":
    sys.exit(main())
