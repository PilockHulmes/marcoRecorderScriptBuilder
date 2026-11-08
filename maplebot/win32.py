"""Win32 窗口相关的最小封装（找窗口、取矩形、判断是否可截屏）。

只做一件事：把原来散在 `capture.py` 里的 ctypes 样板集中到一处。
"""

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32

# 让截屏与鼠标坐标都基于物理像素，避免系统缩放导致偏移。
# 原 capture.py 在 import 时调用，这里保持一致（进程内只需一次）。
user32.SetProcessDPIAware()


def find_window(title):
    """按**精确**标题查找顶层窗口，返回 hwnd；找不到返回 0。"""
    if not title:
        return 0
    return user32.FindWindowW(None, title)


def window_rect(handle):
    """返回 (left, top, right, bottom)；取不到返回 None。负坐标按 0 处理。"""
    if not handle:
        return None
    rect = wintypes.RECT()
    if not user32.GetWindowRect(handle, ctypes.pointer(rect)):
        return None
    return (
        max(0, rect.left),
        max(0, rect.top),
        rect.right,
        rect.bottom,
    )


def is_capturable(handle):
    """窗口存在、可见、且没有最小化——满足这三条才值得开始截屏。"""
    if not handle:
        return False
    return bool(user32.IsWindow(handle)) and bool(user32.IsWindowVisible(handle)) and not user32.IsIconic(handle)


def find_ready_window(title):
    """找到标题匹配且当前可截屏的窗口，返回 hwnd 或 0。"""
    handle = find_window(title)
    return handle if is_capturable(handle) else 0


def wait_for_window(titles, timeout=0.0, poll=0.5, on_wait=None):
    """在 TITLES 里轮询，直到某个窗口可截屏。

    :param titles:   候选窗口标题（精确匹配）。
    :param timeout:  最多等待多少秒；0 表示只看一眼。
    :param poll:     轮询间隔。
    :param on_wait:  可选回调 on_wait(elapsed)，用于打印进度。
    :return:         命中的标题；超时返回 None。
    """
    titles = [t for t in titles if t]
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        for title in titles:
            if find_ready_window(title):
                return title
        if time.monotonic() >= deadline:
            return None
        if on_wait is not None:
            on_wait(time.monotonic() - (deadline - max(0.0, timeout)))
        time.sleep(poll)
