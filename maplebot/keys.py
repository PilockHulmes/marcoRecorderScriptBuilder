"""低误差按键层：直接调 ``SendInput``，没有 pydirectinput 的隐藏 100ms sleep。

为什么不用 pydirectinput：

- 它的 ``PAUSE = 0.1``，每次 ``keyDown``/``keyUp`` 之后都 ``sleep(0.1)``，
  一次"点击"实际 ≈215ms，节奏完全不可控；
- 剩下的时间靠 ``time.sleep``，默认定时器精度 15.6ms，所有延迟都被量化；
- 没法表达"按住 X 毫秒"这种真正需要的原语。

这里只做三件事：扫卡码 ``SendInput``、1ms 定时器、spin 到点就松手。
``dry_run=True`` 时只记录不发送（测试/演练用）。
"""

import ctypes
import time
from ctypes import wintypes

from . import timing

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_winmm = ctypes.WinDLL("winmm")

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_EXTENDEDKEY = 0x0001
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


VK = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "shift": 0x10,
    "ctrl": 0x11, "alt": 0x12, "esc": 0x1B, "space": 0x20,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "delete": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22,
}
for _char in "abcdefghijklmnopqrstuvwxyz":
    VK[_char] = ord(_char.upper())
for _digit in "0123456789":
    VK[_digit] = ord(_digit)
for _i in range(1, 13):
    VK[f"f{_i}"] = 0x70 + _i - 1


def virtual_key(key):
    name = str(key).lower()
    if name in VK:
        return VK[name]
    if len(name) == 1 and name in VK:
        return VK[name]
    raise KeyError(f"不认识的按键：{key!r}")


def time_begin():
    """把系统定时器精度调到 1ms（sleep 才不会被量化成 15.6ms）。"""
    _winmm.timeBeginPeriod(1)


def time_end():
    _winmm.timeEndPeriod(1)


class Keyboard:
    """扫卡码键盘。``dry_run=True`` 只记录事件，不真的发送。"""

    def __init__(self, sleep=None, dry_run=False):
        self._sleep = sleep or timing.sleep_precise
        self.dry_run = bool(dry_run)
        self.events = []          # dry_run 时的记录：(时间, "down"/"up", 键)
        self.pressed = set()

    # ------------------------------------------------------------ 底层
    def _send_key(self, key, up):
        vk = virtual_key(key)
        if self.dry_run:
            self.events.append((time.perf_counter(), "up" if up else "down", str(key)))
            return
        scan = _user32.MapVirtualKeyW(vk, 0)
        inp = _INPUT(type=INPUT_KEYBOARD)
        inp.ki.wVk = 0
        inp.ki.wScan = scan
        inp.ki.dwFlags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
        _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

    def _send_mouse(self, flags, x=0, y=0):
        if self.dry_run:
            self.events.append((time.perf_counter(), f"mouse:{flags}", (x, y)))
            return
        inp = _INPUT(type=0)          # 0 = INPUT_MOUSE
        inp.mi.dx = int(x)
        inp.mi.dy = int(y)
        inp.mi.dwFlags = flags
        _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

    # ------------------------------------------------------------ 原语
    def down(self, key):
        from . import stop

        stop.check()
        self._send_key(key, up=False)
        self.pressed.add(str(key).lower())

    def up(self, key):
        self._send_key(key, up=True)
        self.pressed.discard(str(key).lower())

    def tap(self, key, hold=0.04):
        """按下 → 按住 hold 秒 → 松开。hold 默认 40ms（约 2~3 帧）。"""
        self.down(key)
        try:
            self._sleep(hold)
        finally:
            self.up(key)

    def hold(self, key, seconds):
        self.tap(key, hold=seconds)

    def burst(self, key, count=3, hold=0.04, gap=0.06):
        """连按多次，每下都保证按住 hold、间隔 ≥ gap（防吞键）。"""
        for index in range(max(1, int(count))):
            self.tap(key, hold=hold)
            if index + 1 < count:
                self._sleep(gap)

    def click(self, x, y):
        """绝对坐标左键单击。"""
        self._send_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, x, y)
        self._sleep(0.02)
        self._send_mouse(MOUSEEVENTF_LEFTDOWN)
        self._sleep(0.03)
        self._send_mouse(MOUSEEVENTF_LEFTUP)

    def release_all(self):
        """把所有还按着的键松开（退出/急停时用）。"""
        for key in list(self.pressed):
            try:
                self._send_key(key, up=True)
            except Exception:
                pass
        self.pressed.clear()


class precise_timer:
    """临时把系统定时器精度提到 1ms，退出时保证恢复（异常也恢复、可嵌套）。

    只在真正需要毫秒级按住的动作前后使用；长时间持有会抬高整机时钟中断频率。
    """

    _depth = 0

    def __enter__(self):
        if precise_timer._depth == 0:
            time_begin()
        precise_timer._depth += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        precise_timer._depth = max(0, precise_timer._depth - 1)
        if precise_timer._depth == 0:
            time_end()
        return False


_shared = None


def shared(dry_run=False):
    """进程级共享实例（脚本里 import 后直接用模块函数即可）。"""
    global _shared
    if _shared is None:
        _shared = Keyboard(dry_run=dry_run)
    return _shared


# ---------------------------------------------------------------- 模块级快捷方式
def keyDown(key):
    shared().down(key)


def keyUp(key):
    shared().up(key)


def press(key, hold=0.04):
    shared().tap(key, hold=hold)


def tap(key, hold=0.04):
    shared().tap(key, hold=hold)


def burst(key, count=3, hold=0.04, gap=0.06):
    shared().burst(key, count=count, hold=hold, gap=gap)


def click(x, y):
    shared().click(x, y)


def write(text, hold=0.02, gap=0.03):
    """逐字符输入（大写用 shift）。"""
    keyboard = shared()
    for char in str(text):
        if char.isalpha() and char.isupper():
            keyboard.down("shift")
            keyboard.tap(char.lower(), hold=hold)
            keyboard.up("shift")
        else:
            keyboard.tap(char, hold=hold)
        keyboard._sleep(gap)


def release_all():
    shared().release_all()


__all__ = [
    "Keyboard",
    "burst",
    "click",
    "keyDown",
    "keyUp",
    "press",
    "precise_timer",
    "release_all",
    "shared",
    "tap",
    "time_begin",
    "time_end",
    "virtual_key",
    "write",
]
