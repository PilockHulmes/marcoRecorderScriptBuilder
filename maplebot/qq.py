"""把截图发到 QQ 群（默认 ``dry_run=True``：贴图到输入框但不按回车，绝不发送）。

用途：挂机监测出现时，先把**游戏窗口截图**发到群里，作为"人在屏幕前"的证据。

实测（`cat_qq_screenshot.png`，1067×905 的 QQ 窗口）：
- 群聊窗口标题形如 ``猫叶物语T (1002)``，用**子串匹配**找窗口；
- 输入框在窗口底部，相对位置约 (0.45, 0.90)；
- 贴图靠剪贴板（CF_DIB）+ ``Ctrl+V``，然后 ``Enter`` 发送。

⚠️ 测试时务必保持 ``dry_run=True``（或把 ``group_title`` 指向"文件传输助手"），
否则会把测试截图真的发到群里。
"""

import io
import time
from dataclasses import dataclass

DEFAULT_GROUP = "猫叶物语T"
#: 输入框在窗口内的相对位置（右下角小块区域）
DEFAULT_INPUT_BOX = (0.45, 0.90)


def find_chat_title(fragment, titles=None):
    """在窗口标题列表里找包含 ``fragment`` 的那个；找不到返回 None。"""
    if titles is None:
        import pygetwindow as gw

        titles = gw.getAllTitles()
    for title in titles:
        if title and fragment in title:
            return str(title)
    return None


def set_clipboard_image(png_bytes):
    """把 PNG 放进剪贴板（CF_DIB），QQ 里 Ctrl+V 就能贴图。"""
    from PIL import Image
    import win32clipboard

    image = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, "BMP")
    dib = buffer.getvalue()[14:]          # 去掉 14 字节 BMP 文件头，剩下 DIB
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib)
    finally:
        win32clipboard.CloseClipboard()


@dataclass
class SendResult:
    sent: bool
    reason: str
    window: str = ""


class QQSender:
    """把一张 PNG 发到指定群聊窗口。

    :param dry_run: True 时只贴图（随后清空输入框），**不按回车**——测试用
    :param find_window: ``(fragment) -> (x, y, w, h) | None``
    :param activate: ``(fragment) -> bool``
    :param click: ``(x, y) -> None``
    :param hotkey: ``(keys) -> None``，默认 pydirectinput
    :param set_clipboard: ``(png_bytes) -> None``
    """

    def __init__(
        self,
        group_title=DEFAULT_GROUP,
        dry_run=True,
        input_box=DEFAULT_INPUT_BOX,
        sleep=None,
        find_window=None,
        activate=None,
        click=None,
        hotkey=None,
        set_clipboard=None,
    ):
        self.group_title = group_title
        self.dry_run = bool(dry_run)
        self.input_box = tuple(input_box)
        self._sleep = sleep or time.sleep
        self._find_window = find_window or _pygetwindow_rect
        self._activate = activate or _pygetwindow_activate
        self._click = click or _pydirectinput_click
        self._hotkey = hotkey or _pydirectinput_hotkey
        self._set_clipboard = set_clipboard or set_clipboard_image
        self.last = None

    def send(self, png_bytes):
        """返回 :class:`SendResult`；任何一步失败都返回 ``sent=False``。"""
        rect = self._find_window(self.group_title)
        if rect is None:
            return self._finish(False, "window_not_found")
        if not self._activate(self.group_title):
            return self._finish(False, "activate_failed")

        x, y, w, h = rect
        self._click(int(x + w * self.input_box[0]), int(y + h * self.input_box[1]))
        self._sleep(0.15)
        try:
            self._set_clipboard(png_bytes)
        except Exception as exc:                      # 剪贴板可能被别的程序占用
            return self._finish(False, f"clipboard_failed:{type(exc).__name__}")
        self._hotkey(("ctrl", "v"))
        self._sleep(0.5)

        if self.dry_run:
            # 测试模式：清掉输入框里的图，绝不发送
            self._hotkey(("ctrl", "a"))
            self._hotkey(("delete",))
            return self._finish(True, "dry_run")

        self._hotkey(("enter",))
        self._sleep(0.2)
        return self._finish(True, "sent")

    def _finish(self, sent, reason):
        self.last = SendResult(sent=sent, reason=reason, window=self.group_title)
        print(f"[qq] {reason} (dry_run={self.dry_run}, 群={self.group_title})")
        return self.last


# ---------------------------------------------------------------- 真实实现
def _pygetwindow_rect(fragment):
    import pygetwindow as gw

    for window in gw.getWindowsWithTitle(fragment):
        if window.width > 200 and window.height > 200:
            return (window.left, window.top, window.width, window.height)
    return None


def _pygetwindow_activate(fragment):
    import pygetwindow as gw

    for window in gw.getWindowsWithTitle(fragment):
        try:
            window.activate()
            return True
        except Exception:
            continue
    return False


def _pydirectinput_click(x, y):
    import pydirectinput

    pydirectinput.click(x, y)


def _pydirectinput_hotkey(keys):
    import pydirectinput

    for key in keys:
        pydirectinput.keyDown(key)
    for key in reversed(keys):
        pydirectinput.keyUp(key)


__all__ = [
    "DEFAULT_GROUP",
    "DEFAULT_INPUT_BOX",
    "QQSender",
    "SendResult",
    "find_chat_title",
    "set_clipboard_image",
]
