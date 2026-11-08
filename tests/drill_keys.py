"""按键标定演练：在游戏聊天输入框里打字，用"输入行墨迹量"判断有没有吞键。

安全前提（由使用者保证）：聊天频道是「队伍」且不在队伍中，所以即使误发也无人可见。
本脚本仍然**从不按 Enter**，收尾用 Esc。

用法::

    # 只看计划，不发送任何按键
    .\\venv\\Scripts\\python.exe tests\\drill_keys.py --plan

    # 真正跑标定（会切焦点到游戏并打字！）
    .\\venv\\Scripts\\python.exe tests\\drill_keys.py --live --chars 20

结果写到 detections/key_calibration.csv。
"""

import argparse
import ctypes
import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maplebot import botcheck, keys, settings  # noqa: E402

CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"
HOLDS = (0.02, 0.03, 0.04, 0.06)
GAPS = (0.04, 0.06, 0.10)
ANCHOR_KEYWORDS = ("隊伍", "队伍", "所有人", "全部")


def focus_window(title):
    hwnd = ctypes.windll.user32.FindWindowW(None, title)
    if not hwnd:
        return False
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    return ctypes.windll.user32.GetForegroundWindow() == hwnd


def grab_chat():
    import mss
    import numpy as np

    rect = botcheck._window_rect(settings.chat_window_title()) or botcheck.find_chat_rect()
    if rect is None:
        return None
    x, y, w, h = rect
    with mss.mss() as sct:
        shot = sct.grab({"left": x, "top": y, "width": w, "height": h})
        return np.array(shot)[:, :, :3].copy()


def find_anchor(frame, upscale=2.5):
    """在聊天窗底部找「向隊伍」这行（OCR 常把它认成「向际伍」，所以做宽松匹配）。"""
    if frame is None:
        return None
    import logging

    import cv2
    from paddleocr import PaddleOCR

    height, width = frame.shape[:2]
    offset = int(height * 0.75)
    strip = frame[offset:, :]
    big = cv2.resize(strip, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    logging.getLogger("ppocr").setLevel(logging.ERROR)
    result = PaddleOCR(lang="ch", show_log=False).ocr(big)
    if not result or not result[0]:
        return None
    for line in result[0]:
        text = str(line[1][0])
        looks_like_channel = text.startswith("向") or any(w in text for w in ("隊伍", "队伍"))
        if not looks_like_channel or len(text) > 5:
            continue
        box = line[0]
        xs = [point[0] / upscale for point in box]
        ys = [point[1] / upscale for point in box]
        return (int(min(xs)), int(min(ys)) + offset,
                int(max(xs) - min(xs)), int(max(ys) - min(ys)))
    return None


def ink(frame, anchor):
    """锚点右侧那条输入行的"亮像素"数量（越多说明字越多）。"""
    if frame is None or anchor is None:
        return 0
    x, y, w, h = anchor
    height, width = frame.shape[:2]
    band = frame[max(0, y - 2):min(height, y + h + 2), min(width, x + w + 4):]
    if band.size == 0:
        return 0
    gray = band.max(axis=2)
    return int((gray >= 200).sum())


def clear_input(keyboard, anchor, frame_getter, presses=40):
    keyboard.burst("backspace", count=presses, hold=0.02, gap=0.01)


def run(holds, gaps, chars, live):
    game = settings.window_title()
    if live and not focus_window(game):
        print(f"无法把窗口切到前台：{game}")
        return 1
    frame = grab_chat()
    if frame is None:
        print("找不到聊天窗口，先确认它是独立窗口（MAPLESTORY CHAT）")
        return 1
    anchor = find_anchor(frame)
    if anchor is None:
        print("没找到「向隊伍」锚点")
        return 1
    print(f"锚点 {anchor}，当前墨迹 {ink(frame, anchor)}")

    if not live:
        print("--plan 模式：不发送任何按键")
        return 0

    keyboard = keys.Keyboard()
    rows = []
    for hold in holds:
        for gap in gaps:
            keyboard.burst("backspace", count=40, hold=0.02, gap=0.01)
            time.sleep(0.3)
            base = ink(grab_chat(), anchor)
            ok = 0
            for index in range(chars):
                char = CHARS[index % len(CHARS)]
                with keys.precise_timer():
                    keyboard.tap(char, hold=hold)
                keyboard._sleep(gap)
                now = ink(grab_chat(), anchor)
                if now > base + 1:
                    ok += 1
                    base = now
            keyboard.burst("backspace", count=chars + 10, hold=0.02, gap=0.01)
            keyboard._send_key("esc", up=False)
            keyboard._send_key("esc", up=True)
            rows.append((hold, gap, ok, chars, ok / chars))
            print(f"hold={hold:.2f} gap={gap:.2f} -> {ok}/{chars} ({ok / chars:.0%})")

    out = ROOT / "detections" / "key_calibration.csv"
    out.parent.mkdir(exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["hold", "gap", "ok", "total", "rate"])
        writer.writerows(rows)
    print(f"结果已写入 {out}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="按键标定演练")
    parser.add_argument("--live", action="store_true", help="真的切焦点并打字")
    parser.add_argument("--plan", action="store_true", help="只检查环境，不按键")
    parser.add_argument("--chars", type=int, default=20)
    args = parser.parse_args(argv)
    return run(HOLDS, GAPS, args.chars, live=args.live)


if __name__ == "__main__":
    sys.exit(main())
