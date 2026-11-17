"""日志：让使用者遇到问题时发一个 .log 文件过来就能查。

日志文件放在程序旁边的 ``logs/``（exe 版就是 exe 同目录），同时把所有 ``print``
输出也抄一份进去——这样现有的打印不用改，照样进日志。

用法：

    from maplebot import logbook
    logbook.setup()                      # 一般在启动最早处调用一次
    logbook.log_startup(paths_module)    # 写一行启动信息
    logbook.log_event("標定", 尺度=1.4, 得分=0.97)

隐私：只记录游戏状态和程序行为（地图、商人、价格、耗时、错误），**不截屏、
不读角色名、不记录任何账号信息**。日志第一行会写明这一点。
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import sys
import time
import traceback
from pathlib import Path

#: 单个日志文件上限，超过就换新文件
MAX_BYTES = 2 * 1024 * 1024
#: 最多保留几个日志文件
KEEP = 5
#: 文件名前缀
PREFIX = "assistant"

_logfile = None
_path = None
_original_stdout = None
_original_stderr = None


class _LogFile:
    """带大小上限的日志文件；写超了就换一个新文件。"""

    def __init__(self, directory, prefix=PREFIX, keep=KEEP, max_bytes=MAX_BYTES):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.prefix = prefix
        self.keep = keep
        self.max_bytes = max_bytes
        self._handle = None
        self._size = 0
        self.path = None
        self._rotate()

    def _old_files(self):
        return sorted(self.directory.glob(f"{self.prefix}-*.log"),
                      key=lambda item: item.stat().st_mtime)

    def _rotate(self):
        if self._handle is not None:
            try:
                self._handle.close()
            except Exception:
                pass
        existing = self._old_files()
        # 新文件马上要创建，所以旧文件最多留 keep-1 个
        excess = max(0, len(existing) - (self.keep - 1))
        for old in existing[:excess]:
            try:
                old.unlink()
            except OSError:
                pass
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.path = self.directory / f"{self.prefix}-{stamp}.log"
        index = 1
        while self.path.exists():                     # 同一秒内重启
            self.path = self.directory / f"{self.prefix}-{stamp}-{index}.log"
            index += 1
        self._handle = open(self.path, "a", encoding="utf-8", buffering=1)
        self._size = 0

    def write(self, text):
        if not text:
            return 0
        if self._size + len(text) > self.max_bytes:
            self._rotate()
            self._size = 0
        try:
            self._handle.write(text)
            self._size += len(text)
            self._handle.flush()          # 崩溃时也要留下最后几行
        except Exception:
            return len(text)
        return len(text)

    def flush(self):
        try:
            self._handle.flush()
        except Exception:
            pass

    def close(self):
        try:
            self._handle.close()
        except Exception:
            pass


class _Tee:
    """把写入同时送到原控制台和日志文件。"""

    def __init__(self, original, logfile):
        self.original = original
        self.logfile = logfile

    def write(self, text):
        if self.original is not None:
            try:
                self.original.write(text)
            except Exception:
                pass
        self.logfile.write(text)
        return len(text)

    def flush(self):
        if self.original is not None:
            try:
                self.original.flush()
            except Exception:
                pass
        self.logfile.flush()

    def isatty(self):
        return False


def stamp():
    return time.strftime("%H:%M:%S")


def log_event(tag, **fields):
    """写一行结构化日志（字段按 key=value 拼接）。"""
    if _logfile is None:
        return
    parts = " ".join(f"{key}={value}" for key, value in fields.items())
    _logfile.write(f"{stamp()} [{tag}] {parts}\n")


def setup(directory=None, keep=KEEP, max_bytes=MAX_BYTES):
    """开始记日志，返回日志文件路径。

    ``directory`` 默认是程序旁边的 ``logs/``；不可写时退到数据目录。
    """
    global _logfile, _path, _original_stdout, _original_stderr
    if _logfile is not None:
        return _path

    from . import paths as paths_module

    folder = Path(directory) if directory else paths_module.exe_dir() / "logs"
    try:
        _logfile = _LogFile(folder, keep=keep, max_bytes=max_bytes)
    except OSError:
        _logfile = _LogFile(paths_module.data_root() / "logs", keep=keep,
                            max_bytes=max_bytes)

    _path = _logfile.path
    _original_stdout = sys.stdout
    _original_stderr = sys.stderr
    sys.stdout = _Tee(_original_stdout, _logfile)
    sys.stderr = _Tee(_original_stderr, _logfile)

    handler = logging.StreamHandler(_logfile)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))
    root = logging.getLogger()
    root.addHandler(handler)
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)

    sys.excepthook = _excepthook
    import threading
    threading.excepthook = _thread_excepthook
    log_event("日誌", 檔案=str(_path),
              說明="只记录游戏状态和程序行为，不截屏、不读角色名、不记录账号信息")
    return _path


def path():
    return _path


def close():
    """收尾（测试用；正常退出可以直接让系统回收）。"""
    global _logfile, _path
    if _logfile is None:
        return
    logging.getLogger().handlers = [
        h for h in logging.getLogger().handlers
        if not isinstance(h, logging.StreamHandler)
        or getattr(h, "stream", None) is not _logfile]
    if _original_stdout is not None:
        sys.stdout = _original_stdout
    if _original_stderr is not None:
        sys.stderr = _original_stderr
    _logfile.close()
    _logfile = None
    _path = None


def _excepthook(exc_type, exc_value, exc_tb):
    log_event("異常", 類型=getattr(exc_type, "__name__", str(exc_type)),
              訊息=str(exc_value)[:300])
    traceback.print_exception(exc_type, exc_value, exc_tb)
    if _original_stderr is not None:
        try:
            _original_stderr.flush()
        except Exception:
            pass


def _thread_excepthook(args):
    if args.exc_type is SystemExit:
        return
    log_event("執行緒異常", 執行緒=getattr(args.thread, "name", "?"),
              類型=getattr(args.exc_type, "__name__", str(args.exc_type)),
              訊息=str(args.exc_value)[:300])
    traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)


def _screen_size():
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        return f"{user32.GetSystemMetrics(0)}x{user32.GetSystemMetrics(1)}"
    except Exception:
        return "?"


def _package_version(name):
    try:
        from importlib import metadata
        return metadata.version(name)
    except Exception:
        pass
    try:                      # 冻结后 importlib.metadata 找不到，退回读模块属性
        module = __import__(name.split("-")[0])
        return getattr(module, "__version__", "?")
    except Exception:
        return "?"


def _version():
    """版本号：优先读打包时写进 BUILD.txt 的提交号，否则用包版本。"""
    try:
        from . import paths as paths_module
        header = paths_module.resource_root() / "BUILD.txt"
        if header.exists():
            return header.read_text(encoding="utf-8").strip()[:40]
    except Exception:
        pass
    try:
        from . import __version__
        return __version__
    except Exception:
        return "?"


def log_startup(paths_module, **extra):
    """写启动信息：版本、系统、路径、屏幕、依赖版本。"""
    fields = {
        "版本": _version(),
        "打包": paths_module.is_frozen(),
        "時間": time.strftime("%Y-%m-%d %H:%M:%S"),
        "Python": platform.python_version(),
        "系統": platform.platform(),
        "螢幕": _screen_size(),
        "數據目錄": str(paths_module.data_root()),
        "資源目錄": str(paths_module.resource_root()),
        "opencv": _package_version("opencv-python"),
        "numpy": _package_version("numpy"),
        "PID": os.getpid(),
    }
    fields.update(extra)
    log_event("啟動", **fields)


def log_heartbeat(state=None, controller=None, extra=None):
    """周期性心跳：运行时长、帧率、地图、通栏、共享统计。"""
    fields = {}
    if state is not None:
        fields["地圖"] = getattr(state, "map", "") or "?"
        stats = getattr(state, "stats", None) or {}
        fields["金幣"] = stats.get("coins")
        fields["負重"] = f"{stats.get('weight')}/{stats.get('capacity')}"
        fields["提示"] = (getattr(state, "note", "") or "")[:60]
    if controller is not None:
        share = getattr(controller, "share", None)
        if share is not None:
            fields["共享"] = share.stats()
        fields["活躍檔位"] = getattr(controller, "activity_tier", None)
        fields["縮放"] = getattr(controller, "ui_scale", None)
        counters = getattr(controller, "counters", None)
        if counters:
            fields.update(counters)
    if extra:
        fields.update(extra)
    log_event("心跳", **fields)
