"""保证只跑一个实例。

为什么要：两个实例会同时截屏、同时写 ``observations.json``、同时往共享目录上传，
既浪费 CPU 又会互相覆盖数据。

做法：命名互斥体（named mutex）。它由内核持有，进程退出或崩溃时自动释放，
不会像锁文件那样留下"残留锁"。

用 ``Local\\`` 前缀：同一台机器不同 Windows 用户各开一个互不干扰；
``Global\\`` 则是整机唯一。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

ERROR_ALREADY_EXISTS = 183

#: 默认互斥体名字（源码运行和 exe 共用同一个，避免两边同时写数据）
DEFAULT_NAME = "Local\\MapleTrade.App"

#: 主窗口标题（用来把已经开着的实例拉到前台）
WINDOW_TITLE = "小助手"

SW_RESTORE = 9


def _kernel32():
    lib = ctypes.WinDLL("kernel32", use_last_error=True)
    lib.CreateMutexW.restype = wintypes.HANDLE
    lib.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    lib.CloseHandle.argtypes = [wintypes.HANDLE]
    return lib


class SingleInstance:
    """抢一个命名互斥体；抢到返回 True，已有实例返回 False。"""

    def __init__(self, name=DEFAULT_NAME):
        self.name = name
        self._handle = None

    def acquire(self):
        if self._handle:
            return True
        try:
            k32 = _kernel32()
            handle = k32.CreateMutexW(None, False, self.name)
        except Exception:
            return True                    # 拿不到系统 API：放行，别把程序卡死
        if not handle:
            return True
        existed = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
        self._handle = handle
        return not existed

    def release(self):
        if not self._handle:
            return
        try:
            _kernel32().CloseHandle(self._handle)
        except Exception:
            pass
        self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.release()


def activate_running_window(title=WINDOW_TITLE):
    """把已经开着的窗口恢复并拉到前台；找不到窗口返回 False。"""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            return False
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False
