import win32gui
import win32con
import threading
import time

import capture

# 配置目标窗口标题（根据实际情况修改）
target_window_title = capture.WINDOW_NAME

# 同步变量
paused = False

# 事件回调函数
def event_callback(hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
    global paused
    if event == win32con.EVENT_SYSTEM_FOREGROUND:
        # 获取窗口标题
        window_title = win32gui.GetWindowText(hwnd)
        # 判断是否为目标窗口
        if target_window_title in window_title:
            paused = False
            print("[回调] 检测到目标窗口，恢复程序")
        else:
            paused = True
            print("[回调] 目标窗口未激活，暂停程序")

# 设置全局事件钩子
win32gui.SetWinEventHook(
    win32con.EVENT_SYSTEM_FOREGROUND,  # 监听前台窗口变化
    win32con.EVENT_SYSTEM_FOREGROUND,
    0,  # 监控所有进程
    event_callback,
    0,
    0,
    win32con.WINEVENT_OUTOFCONTEXT | win32con.WINEVENT_SKIPOWNPROCESS
)
