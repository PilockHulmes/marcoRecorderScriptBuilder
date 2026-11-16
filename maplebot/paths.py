"""运行期数据的落盘位置。

为什么需要这个模块：打包成单文件 exe 后，程序里的"项目目录"指向
PyInstaller 解压出来的临时目录（``_MEIPASS``），exe 一退出就被删掉。
如果还往那里写，用户跑出来的记录、学到的模板每次退出都会消失。

所以把两类路径分开：

- **只读资源**（``RES_ROOT``）：图标、数字模板、预置地图名，都打包进 exe；
- **可写数据**（``DATA_ROOT``）：观察记录、新学的模板，放用户能久留的地方。

``DATA_ROOT`` 的选法（按顺序）：

1. exe 旁边有 ``portable.txt`` → 用 exe 目录下的 ``data``；
2. exe 旁边有 ``localdata.txt`` → 用 ``%LOCALAPPDATA%\\MapleTrade\\data``；
3. 能往 exe 目录写 → 就用 exe 目录下的 ``data``（便携，数据跟着文件夹走）；
4. 写不进去（``C:\\Program Files`` 之类）→ 退到 ``%LOCALAPPDATA%\\MapleTrade\\data``。

首次启动时把只读资源里的种子数据（约 4.6 MB）复制到 ``DATA_ROOT``，
只补齐缺失的文件，绝不覆盖用户已有的数据。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

#: 用户目录下的文件夹名
APP_NAME = "MapleTrade"

_resolved = {}


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def exe_dir():
    """exe 所在目录；源码运行时就是项目根目录。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_root():
    """只读资源的根：打包后是 ``_MEIPASS``，源码运行时是项目根。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", exe_dir()))
    return Path(__file__).resolve().parents[1]


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=str(folder), prefix=".probe_", delete=True):
            return True
    except Exception:
        return False


def data_root():
    """可写数据的根目录（``<root>/data``）。结果会缓存。"""
    if "data_root" in _resolved:
        return _resolved["data_root"]

    override = os.environ.get("MAPLE_TRADE_DATA")
    if override:
        root = Path(override).expanduser().resolve()
        _resolved["data_root"] = root
        root.mkdir(parents=True, exist_ok=True)
        ensure_seed(root)
        return root

    base = exe_dir()
    has_portable = (base / "portable.txt").exists()
    has_localdata = (base / "localdata.txt").exists()

    if has_portable and _writable(base):
        root = base / "data"                     # 强制便携
    elif has_localdata:
        root = _localappdata()                   # 强制用户目录
    elif _writable(base):
        root = base / "data"                     # 默认：能写就放 exe 旁边
    else:
        root = _localappdata()                   # Program Files 之类

    root.mkdir(parents=True, exist_ok=True)
    ensure_seed(root)
    _resolved["data_root"] = root
    return root


def _localappdata() -> Path:
    base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    return Path(base) / APP_NAME / "data"


def trade_dir() -> Path:
    """跑商数据目录（原来是项目里的 ``data/trade``）。"""
    return data_root() / "trade"


def ensure_seed(root: Path):
    """把只读资源里的种子数据补到可写目录（只补缺失的文件）。"""
    source = resource_root() / "data"
    if not source.is_dir():
        return
    target = Path(root)
    if source.resolve() == target.resolve():
        return                      # 源码运行：本来就是同一个地方
    for item in source.rglob("*"):
        if not item.is_file():
            continue
        relative = item.relative_to(source)
        destination = target / relative
        if destination.exists():
            continue
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
        except Exception:
            pass


def describe():
    """给启动日志用的一行说明。"""
    return f"数据目录：{data_root()}（资源目录：{resource_root()}）"
