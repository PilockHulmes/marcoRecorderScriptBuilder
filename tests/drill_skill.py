"""技能按键标定：F（普攻）→ 等待 interval → G（跳跃）。判断跳跃有没有被吞。

判据：按 G 之后小地图上角色黄点会向上弹，抓 0.6 秒内的 y 最小值，
比基线高 3px 以上就算跳起来了。

用法::

    .\\venv\\Scripts\\python.exe tests\\drill_skill.py --plan     # 只查窗口和小地图
    .\\venv\\Scripts\\python.exe tests\\drill_skill.py          # 真按键
"""

import argparse
import ctypes
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maplebot import keys, minimap, player, settings  # noqa: E402

INTERVALS = (0.05, 0.10, 0.15, 0.20, 0.30, 0.50)
REPS = 5
JUMP_WINDOW = 0.7
JUMP_MIN_RISE = 3


def game_rect():
    import win32gui

    best = None
    for title in settings.window_titles():
        found = []
        def callback(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            if win32gui.GetWindowText(hwnd) != title:
                return
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            if right - left > 300 and bottom - top > 300:
                found.append((hwnd, (left, top, right - left, bottom - top)))
        win32gui.EnumWindows(callback, None)
        if found:
            hwnd, rect = max(found, key=lambda item: item[1][2] * item[1][3])
            if best is None or rect[2] * rect[3] > best[1][2] * best[1][3]:
                best = (hwnd, rect)
    return best


def focus(hwnd):
    import win32con
    import win32gui

    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    return win32gui.GetForegroundWindow() == hwnd


def grab(rect):
    import mss
    import numpy as np

    x, y, w, h = rect
    with mss.mss() as sct:
        shot = sct.grab({"left": x, "top": y, "width": w, "height": h})
        return np.array(shot)[:, :, :3].copy()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--reps", type=int, default=REPS)
    parser.add_argument("--intervals", default="")
    args = parser.parse_args(argv)

    found = game_rect()
    if not found:
        print("找不到游戏窗口")
        return 1
    hwnd, window = found
    print("游戏窗口:", window)

    with_focus = focus(hwnd)
    print("切焦点成功:", with_focus)

    frame = grab(window)
    box = minimap.find_minimap(frame)
    if box is None:
        print("游戏窗口里没找到小地图")
        return 1
    inner = box.inner().as_tuple()
    print("小地图内容区(窗口内坐标):", inner)

    screen_rect = (window[0] + inner[0], window[1] + inner[1], inner[2], inner[3])
    content = (0, 0, inner[2], inner[3])

    def player_y():
        candidates = player.find_candidates(grab(screen_rect), content)
        return candidates[0].y if candidates else None

    def scroll_y():
        """地图特征（非玩家）的 y：跳跃时小地图会滚动，玩家点本身不动。"""
        candidates = player.find_candidates(grab(screen_rect), content)
        if len(candidates) < 2:
            return None
        return sorted(candidates, key=lambda c: c.score, reverse=True)[1].y

    baseline = player_y()
    print("角色基线 y:", baseline)
    if baseline is None:
        return 1
    if args.plan:
        return 0
    if not with_focus:
        print("焦点没切过去，中止")
        return 1

    keyboard = keys.Keyboard()
    intervals = (tuple(float(v) for v in args.intervals.split(","))
                 if args.intervals else INTERVALS)
    rows = []
    for interval in intervals:
        hits = 0
        for _ in range(args.reps):
            start = scroll_y() or 0
            keyboard.tap("f", hold=0.04)
            keyboard._sleep(interval)
            keyboard.tap("g", hold=0.04)
            peak = start
            deadline = time.perf_counter() + JUMP_WINDOW
            while time.perf_counter() < deadline:
                y = scroll_y()
                if y is not None and y > peak:
                    peak = y
                time.sleep(0.01)
            if peak - start >= JUMP_MIN_RISE:
                hits += 1
            keyboard._sleep(0.6)
        rows.append((interval, hits, args.reps))
        print(f"F→等待 {interval*1000:.0f}ms→G : {hits}/{args.reps}")

    out = ROOT / "detections" / "skill_calibration.csv"
    out.parent.mkdir(exist_ok=True)
    out.write_text("interval,ok,total\n" + "".join(f"{a},{b},{c}\n" for a, b, c in rows),
                   encoding="utf-8")
    print("结果写入", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
