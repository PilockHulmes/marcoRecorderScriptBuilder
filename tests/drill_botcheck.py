"""受控演练：把一张 detection 截图显示在屏幕上，用**真实截屏**跑一遍链路。

不碰 QQ、不碰游戏：证据只存本地，输入走假按键（除非加 ``--type``）。

用法::

    # 1) 先在另一个窗口里显示一张截图（模拟游戏里的面板）
    .\\venv\\Scripts\\python.exe -c "import cv2; img=cv2.imread('detection1.png'); cv2.imshow('drill', img); cv2.waitKey(0)"

    # 2) 跑演练（检测 + 取证 + 读码 + 点击）
    .\\venv\\Scripts\\python.exe tests\\drill_botcheck.py

    # 3) 想验证"真的能打字"，先打开记事本并点一下，再：
    .\\venv\\Scripts\\python.exe tests\\drill_botcheck.py --type
"""

import argparse
import ctypes
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:            # 允许直接 python tests/drill_botcheck.py
    sys.path.insert(0, str(ROOT))

from maplebot import botcheck, qq, rune_api  # noqa: E402


class RecordingKeys:
    """记录"本来会按什么"，不真的按键。"""

    def __init__(self):
        self.events = []

    def keyDown(self, key):
        self.events.append(("down", key))

    def keyUp(self, key):
        self.events.append(("up", key))

    def typed(self):
        ignore = {"shift", "ctrl", "alt"}
        return "".join(k for e, k in self.events if e == "down" and k not in ignore)


def grab_screen():
    import mss

    with mss.mss() as sct:
        monitor = sct.monitors[1]
        shot = sct.grab(monitor)
        import numpy as np

        return np.array(shot)[:, :, :3].copy()


def cursor_position():
    point = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def main(argv=None):
    parser = argparse.ArgumentParser(description="挂机监测链路的受控演练")
    parser.add_argument("--click", action="store_true", help="真的点击（默认只移动鼠标并核对坐标）")
    parser.add_argument("--type", action="store_true", help="真的把验证码打进当前焦点窗口")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--image", default=str(ROOT / "detection1.png"))
    args = parser.parse_args(argv)

    import ctypes.wintypes  # noqa: F401  (GetCursorPos 需要)

    print("=== 1. 截取当前屏幕 ===")
    frame = grab_screen()
    print(f"屏幕 {frame.shape[1]}x{frame.shape[0]}")

    print("=== 2. 找面板 ===")
    panel = botcheck.find_panel(frame)
    if panel is None:
        print("没找到面板（屏幕上那张图显示出来了吗？坐标/缩放对不上？）")
        print("试试 OCR 兜底…")
        panel, source = botcheck.find_panel_any(frame, verify=True)
        print(f"OCR 结果：{source} {panel}")
        if panel is None:
            return 1
    else:
        print(f"模板命中：{panel}")

    print("=== 3. 取证（只存本地） ===")
    out_dir = ROOT / "detections"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"drill_{time.strftime('%Y%m%d_%H%M%S')}.png"
    path.write_bytes(rune_api.encode_png(frame))
    print(f"已保存 {path} ({path.stat().st_size // 1024} KB)")

    print("=== 4. 读验证码（真实 API，三次一致） ===")
    crop = botcheck.captcha_crop(frame, panel)
    captcha = botcheck.read_captcha(crop, attempts=args.attempts)
    print(f"识别结果：{captcha!r}（None = 三次不一致/看不清，按设计不会输入）")

    print("=== 5. 点击「請先點擊再輸入」 ===")
    x, y = panel.click_point
    import pydirectinput

    pydirectinput.moveTo(x, y)          # 只移动，不点击：避免误触到 QQ/游戏
    time.sleep(0.2)
    print(f"目标点 ({x}, {y}) → 鼠标实际位置 {cursor_position()}")
    if args.click:
        guard = botcheck.BotCheckGuard(
            capture_frame=grab_screen,
            send_evidence=lambda png: (out_dir / "drill_guard.png").write_bytes(png) and True,
            click=lambda cx, cy: (print(f"（真点击 {cx},{cy}）"), pydirectinput.click(cx, cy)),
            key_api=RecordingKeys(),
            vision_client=None,
            attempts=args.attempts,
            verify_timeout=0.0,
            sleep=time.sleep,
        )
        result = guard.handle()
        print(f"guard 结果：handled={result.handled} reason={result.reason} captcha={result.captcha!r}")
    else:
        print("（未加 --click，跳过真实点击）")

    if captcha is None:
        print("验证码没读出来，按要求不输入。")
        return 0

    print("=== 6. 输入 ===")
    if args.type:
        print("真实输入到当前焦点窗口（3 秒后开始，请切到记事本）")
        time.sleep(3)
        botcheck.type_text(captcha)
        print(f"已输入 {captcha!r} 并回车")
    else:
        keys = RecordingKeys()
        botcheck.type_text(captcha, key_api=keys, sleep=lambda _s: None)
        print(f"（演练）本应输入：{keys.typed()!r}")

    print("=== 7. 顺带检查 QQ 窗口（只读，不发送） ===")
    rect = qq._pygetwindow_rect(qq.DEFAULT_GROUP)
    print(f"QQ 群窗口：{rect if rect else '没找到（QQ 没开或群名不对）'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
