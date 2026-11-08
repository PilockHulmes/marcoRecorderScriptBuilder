"""全局急停：一个 stop key、一次会话、退出时保证按键都被松开。

设计要点（为什么不是「在每个脚本里塞一个 while 条件」）：

1. 仓库里有 40 多个 `while True:` 的脚本，逐个改造风险大、忘掉一个就失效；
2. 所有动作最终都会经过 `pydirectinput.*` 或 `time.sleep`，所以**在这两类入口上
   检查停止标记**，就能把任意脚本的 `while True` 展开：

.. code-block:: python

    with stop.session(stop_key="l"):        # run.py 里使用
        runpy.run_path("s2_clp.py")         # 脚本内部照旧写 while True

3. 停止时抛 :class:`StopScript`（继承 ``BaseException``，脚本里的
   ``except Exception`` 吞不掉），由 :mod:`maplebot.runner` 捕获后收尾；
4. 按下过哪些键会被记账，退出时逐个松开，避免「脚本停了但角色还在往右跑」。
"""

import contextlib
import threading
import time as _time

# 默认急停键（小写/大写都认）
STOP_KEY = "l"

# 停止标记的轮询粒度：越小响应越快，越大越省 CPU
CHECK_INTERVAL = 0.05

# 需要包一层「先检查停止」的 pydirectinput 入口
KEYBOARD_API = ("keyDown", "keyUp", "press", "write")
MOUSE_API = (
    "click",
    "doubleClick",
    "tripleClick",
    "mouseDown",
    "mouseUp",
    "moveTo",
    "moveRel",
    "move",
    "scroll",
    "hscroll",
    "vscroll",
)


class StopScript(BaseException):
    """急停信号，只应由 :mod:`maplebot.stop` 抛出。"""


_lock = threading.Lock()
_stopped = threading.Event()
_reason = ""
_pressed_keys = set()
_pressed_buttons = set()
_patched = []          # [(module, name, original)]
_orig_key_up = None
_orig_mouse_up = None
_listener = None
_real_sleep = _time.sleep


# ---------------------------------------------------------------- 状态查询
def is_stopped():
    return _stopped.is_set()


def reason():
    return _reason


def check():
    """停止后调用任意受控 API 就会抛 :class:`StopScript`。"""
    if _stopped.is_set():
        raise StopScript(_reason or "stop requested")


def request_stop(reason_text=""):
    """请求停止。多个触发源（stop key / Ctrl+C / 定时器）都调这里。"""
    global _reason
    with _lock:
        if not _stopped.is_set():
            _reason = reason_text or "requested"
            _stopped.set()
    _silence_alarm()


def _silence_alarm():
    """正在播警报音时立刻掐掉，免得 stop 之后还要等 mp3 放完。"""
    try:
        import os

        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import pygame

        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
    except Exception:
        pass


# ---------------------------------------------------------------- 打补丁
def _wrap(name, fn):
    def wrapper(*args, **kwargs):
        check()
        if name == "keyDown" and args:
            _pressed_keys.add(str(args[0]))
        elif name == "keyUp" and args:
            _pressed_keys.discard(str(args[0]))
        elif name == "mouseDown" and args:
            _pressed_buttons.add(str(args[0]))
        elif name == "mouseUp" and args:
            _pressed_buttons.discard(str(args[0]))
        return fn(*args, **kwargs)

    wrapper.__name__ = getattr(fn, "__name__", name)
    wrapper.__doc__ = getattr(fn, "__doc__", None)
    wrapper.__wrapped__ = fn
    return wrapper


def _patch_pydirectinput():
    global _orig_key_up, _orig_mouse_up
    try:
        import pydirectinput
    except Exception as exc:  # pragma: no cover - 依赖缺失时退化为无急停
        print(f"[stop] 无法导入 pydirectinput（{exc}），急停降级为只停止脚本")
        return

    # 先记住原始函数，再打补丁——收尾松键必须走原始实现，否则会被自己的 check() 拦住
    _orig_key_up = getattr(pydirectinput, "keyUp", None)
    _orig_mouse_up = getattr(pydirectinput, "mouseUp", None)

    for name in KEYBOARD_API + MOUSE_API:
        fn = getattr(pydirectinput, name, None)
        if not callable(fn):
            continue
        _patched.append((pydirectinput, name, fn))
        setattr(pydirectinput, name, _wrap(name, fn))


def _patch_sleep():
    def guarded_sleep(seconds, *args, **kwargs):
        # 只劫持主线程：Capture 这类后台线程在停止时应该正常退出，而不是抛异常
        if threading.current_thread() is not threading.main_thread():
            return _real_sleep(seconds, *args, **kwargs)
        if not isinstance(seconds, (int, float)):
            return _real_sleep(seconds, *args, **kwargs)
        deadline = _time.monotonic() + max(0.0, float(seconds))
        while True:
            if _stopped.is_set():
                raise StopScript(_reason or "stop requested")
            remain = deadline - _time.monotonic()
            if remain <= 0:
                return
            _real_sleep(min(remain, CHECK_INTERVAL))

    _patched.append((_time, "sleep", _real_sleep))
    _time.sleep = guarded_sleep


def _install_listener(stop_key):
    global _listener
    try:
        from pynput import keyboard
    except Exception as exc:  # pragma: no cover
        print(f"[stop] 无法导入 pynput（{exc}），只能靠 Ctrl+C 停止")
        return

    def on_press(key):
        try:
            char = key.char
        except AttributeError:
            return None
        if char and char.lower() == stop_key.lower():
            request_stop(f"stop key {stop_key!r}")
            return False  # 停止监听
        return None

    _listener = keyboard.Listener(on_press=on_press)
    _listener.daemon = True
    _listener.start()


def _uninstall_listener():
    global _listener
    if _listener is None:
        return
    try:
        _listener.stop()
    except Exception:
        pass
    _listener = None


def _restore():
    for module, name, original in _patched:
        try:
            setattr(module, name, original)
        except Exception:
            pass
    _patched.clear()


# ---------------------------------------------------------------- 松键
def release_pressed_keys(verbose=True):
    """把「按下过但没松开」的键/鼠标键全部松开，返回 [(kind, key)]。"""
    released = []
    if _orig_key_up is not None:
        for key in sorted(_pressed_keys):
            try:
                _orig_key_up(key)
                released.append(("key", key))
            except Exception as exc:
                print(f"[stop] 松开按键 {key!r} 失败：{exc}")
    _pressed_keys.clear()

    if _orig_mouse_up is not None:
        for button in sorted(_pressed_buttons):
            try:
                _orig_mouse_up(button)
                released.append(("mouse", button))
            except Exception as exc:
                print(f"[stop] 松开鼠标键 {button!r} 失败：{exc}")
    _pressed_buttons.clear()

    if released and verbose:
        print("[stop] 已松开：" + ", ".join(f"{kind} {name}" for kind, name in released))
    return released


# ---------------------------------------------------------------- 会话
def install(stop_key=STOP_KEY, enabled=True):
    """装上急停：按键监听 + pydirectinput/sleep 补丁。可重复调用（会先复位）。"""
    global _reason
    _restore()  # 清掉上一次没卸干净的补丁，避免叠加包装
    with _lock:
        _stopped.clear()
        _reason = ""
    _pressed_keys.clear()
    _pressed_buttons.clear()
    _patch_sleep()
    _patch_pydirectinput()
    if enabled:
        _install_listener(stop_key)


def uninstall():
    """卸载急停并松开所有按下的键。

    停止标记会清掉（否则下一次会话一启动就立刻触发），但 :func:`reason` 保留，
    方便调用方在收尾时报告「因为什么停的」。
    """
    _uninstall_listener()
    release_pressed_keys()
    _restore()
    _stopped.clear()


@contextlib.contextmanager
def session(stop_key=STOP_KEY, enabled=True):
    """``with stop.session("l"): ...`` —— 退出（含异常）时自动收尾。"""
    install(stop_key=stop_key, enabled=enabled)
    try:
        yield
    finally:
        uninstall()
