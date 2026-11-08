"""测试公用工具：路径、假截屏器、假 pydirectinput、子进程执行。

约定：
- 所有测试都不启动游戏、不注入真实按键、不访问网络；
- 需要「干净进程」的测试（导入副作用、CLI）走 :func:`run_python`；
- 需要假输入的地方统一用 :func:`fake_pydirectinput_source`，生成一段可 exec 的源码。
"""

import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
HAIKU = ROOT / "haikuScripts"
MARCO = ROOT / "marcoRecorder"
AUTO_MAPLE = ROOT / "auto-maple"
ASSETS = HAIKU / "assets"

PY = sys.executable
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}

#: 让测试子进程能 import maplebot / 扁平模块
BOOTSTRAP = f"""
import sys
for p in (r"{ROOT}", r"{HAIKU}"):
    if p not in sys.path:
        sys.path.insert(0, p)
"""


def asset(name, gray=True):
    """读 assets 里的模板。"""
    path = ASSETS / name
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE if gray else cv2.IMREAD_COLOR)
    if img is None:
        raise AssertionError(f"素材缺失：{path}")
    return img


class FakeGrabber:
    """替代 mss 的截图器：grab() 直接返回预置画面。"""

    def __init__(self, frame):
        self.frame = frame
        self.calls = 0

    def grab(self, region, *args, **kwargs):
        self.calls += 1
        return self.frame


def build_frame(width=800, height=600, templates=(), seed=1):
    """造一张带纹理的假画面，并按给定位置贴入模板。

    :param templates: 可迭代的 ``(image, (y, x))``，模板会被贴到指定位置。
    :return: BGR uint8 画面
    """
    rng = np.random.default_rng(seed)
    frame = rng.integers(0, 256, (height, width, 3), dtype=np.uint8)
    for img, (y, x) in templates:
        h, w = img.shape[:2]
        if y + h > height or x + w > width:
            raise AssertionError(f"模板 {img.shape} 放不进画面 ({height}, {width}) 的 ({y}, {x})")
        frame[y:y + h, x:x + w] = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if img.ndim == 2 else img
    return frame


def temp_assets(names):
    """建一个临时素材目录，只复制 NAMES 里的文件；返回 (TemporaryDirectory, 路径)。"""
    tmp = tempfile.TemporaryDirectory(prefix="maplebot-assets-")
    for name in names:
        src = ASSETS / name
        if not src.exists():
            raise AssertionError(f"素材缺失：{src}")
        (Path(tmp.name) / name).write_bytes(src.read_bytes())
    return tmp, Path(tmp.name)


def fake_pydirectinput_source(prelude="", postlude=""):
    """返回一段源码：把假 pydirectinput 装进 sys.modules 并记录调用。

    生成的模块里：
    - ``calls`` 是 ``[(name, *args), ...]``；
    - ``show(label, fn)`` 会清空记录、执行 FN、打印 ``label | name:arg ...``。
    """
    header = textwrap.dedent(
        '''
        import sys, types

        calls = []
        fake = types.ModuleType("pydirectinput")

        def _rec(name):
            def f(*args, **kwargs):
                calls.append((name,) + tuple(str(a) for a in args))
            return f

        for _name in ("keyDown", "keyUp", "press", "write", "click", "doubleClick",
                      "tripleClick", "mouseDown", "mouseUp", "moveTo", "moveRel",
                      "move", "scroll", "hscroll", "vscroll"):
            setattr(fake, _name, _rec(_name))
        sys.modules["pydirectinput"] = fake

        def show(label, fn):
            calls.clear()
            fn()
            print(label, "|", " ".join(f"{c[0]}:{c[1]}" if len(c) > 1 else c[0] for c in calls))
        '''
    )
    return (
        header
        + "\n"
        + textwrap.dedent(prelude)
        + "\n"
        + textwrap.dedent(postlude)
        + "\n"
    )


def run_python(code, cwd=ROOT, env=None, timeout=120):
    """在子进程里跑一段代码（默认自动插入仓库根与 haikuScripts 到 sys.path）。"""
    full = BOOTSTRAP + textwrap.dedent(code)
    return run_python_raw(full, cwd=cwd, env=env, timeout=timeout)


def run_python_raw(code, cwd=ROOT, env=None, timeout=120):
    """在子进程里跑一段代码，不插入任何路径（自己控制 sys.path）。"""
    return subprocess.run(
        [PY, "-c", textwrap.dedent(code)],
        cwd=str(cwd),
        env={**ENV, **(env or {})},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


def run_cli(*args, timeout=120, cwd=ROOT):
    """跑 run.py。"""
    return subprocess.run(
        [PY, str(ROOT / "run.py"), *args],
        cwd=str(cwd),
        env=ENV,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )
