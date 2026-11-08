"""重构自检：不启动游戏、不注入真实按键。

运行：``.\\venv\\Scripts\\python.exe tests\\test_refactor.py``

覆盖点：

1. 全仓库语法（只允许 `auto-maple/src/rune.py` 这一个已知坏文件）；
2. 兼容壳的**模块同一性**：`import config` / `import src.config` / `maplebot.config` 是同一个对象；
3. `Capture` 薄壳的默认值与素材加载（与当前工作目录无关）；
4. `stop` 的急停 + 按键记账 + 松键（用假的 pydirectinput，不碰真实键盘）；
5. `run.py` 脚本解析、`--dry-run`、`--stop-after` 端到端停止。
"""

import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
PY = sys.executable
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}

failures = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok or not detail else f"\n      {detail}"))
    if not ok:
        failures.append(name)


def run_py(code, cwd=ROOT, timeout=180):
    return subprocess.run(
        [PY, "-c", code],
        cwd=str(cwd),
        env=ENV,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


def run_cli(*args, timeout=180):
    return subprocess.run(
        [PY, str(ROOT / "run.py"), *args],
        cwd=str(ROOT),
        env=ENV,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


# ---------------------------------------------------------------- 1. 语法
print("\n[1] 全仓库语法")
sys.path.insert(0, str(ROOT))
from maplebot import runner  # noqa: E402

check("语法检查通过（已知坏文件除外）", runner.check_sources() == 0)
check(
    "已知坏文件只有 rune.py",
    runner.KNOWN_BROKEN == {"auto-maple/src/rune.py"},
    str(runner.KNOWN_BROKEN),
)

# ---------------------------------------------------------------- 2. 模块同一性
print("\n[2] 兼容壳的模块同一性")
IDENTITY_CODE = """
import config
import maplebot.config as shared
print("config", config is shared)
print("has_player_position", config.player_position == (0, 0))
config.window_override = "PROBE"
print("write_visible", shared.window_override == "PROBE")
import utils
print("utils_multimatch", utils.multi_match is __import__("maplebot.utils", fromlist=["x"]).multi_match)
print("utils_config", utils.config is shared)
"""
result = run_py(IDENTITY_CODE, cwd=ROOT / "haikuScripts")
for line in ("config True", "has_player_position True", "write_visible True", "utils_multimatch True", "utils_config True"):
    check(f"haikuScripts {line}", line in result.stdout, result.stdout + result.stderr)

AUTO_MAPLE_CODE = """
import src.config as config
import maplebot.config as shared
print("identity", config is shared)
import src.utils as utils
print("utils_ok", callable(utils.multi_match))
from src.capture import Capture, WINDOW_NAME
print("window_name", WINDOW_NAME)
print("subclass", Capture.__mro__[1].__module__)
c = Capture()
print("flags", c.detect_other, c.detect_rune, c.detect_blackscreen, c.detect_rune_buff, c.detect_bot_testing)
print("interval", c.frame_interval)
print("rune_template", "rune" in c.tpl)
"""
result = run_py(AUTO_MAPLE_CODE, cwd=ROOT / "auto-maple")
for expected in (
    "identity True",
    "utils_ok True",
    "window_name Haiku v224",
    "subclass maplebot.capture",
    "flags True True True True False",
    "interval 0.05",
    "rune_template True",
):
    check(f"auto-maple {expected}", expected in result.stdout, result.stdout + result.stderr)

# ---------------------------------------------------------------- 3. 素材加载与 cwd 无关
print("\n[3] Capture 薄壳 / 素材路径")
CAPTURE_CODE = """
import sys
from capture import Capture, WINDOW_NAME
c = Capture("MapleStory")
print("window", c.window_name)
print("assets_is_absolute", __import__("pathlib").Path(c.assets_dir).is_absolute())
print("tpl", sorted(k for k in c.tpl if not k.endswith("_hw")))
print("flags", c.detect_other, c.detect_rune, c.detect_blackscreen, c.detect_rune_buff, c.detect_bot_testing)
print("interval", c.frame_interval)
print("rate", getattr(c, "minimap_ratio"))
"""
result = run_py(CAPTURE_CODE, cwd=ROOT / "haikuScripts")
check("Capture 默认标题可覆盖", "window MapleStory" in result.stdout, result.stdout + result.stderr)
check("素材目录为绝对路径（不依赖 cwd）", "assets_is_absolute True" in result.stdout, result.stdout + result.stderr)
check("haikuScripts 除找角色外的检测全关", "flags False False False False False" in result.stdout, result.stdout + result.stderr)
check("haikuScripts 截屏间隔 0.1s", "interval 0.1" in result.stdout, result.stdout + result.stderr)

# 换一个工作目录（仓库根）再 import，验证素材路径仍然正确
result = run_py(
    "import sys; sys.path.insert(0, 'haikuScripts');"
    "from capture import Capture; c = Capture(); print('assets', c.assets_dir)",
    cwd=ROOT,
)
check("从仓库根 import 也能找到素材", "haikuScripts" in result.stdout and "assets" in result.stdout, result.stdout + result.stderr)

CAPTURE_ERROR_CODE = """
import sys
from maplebot.capture import load_templates
try:
    load_templates("no_such_dir")
except FileNotFoundError as exc:
    print("error", "素材目录不存在" in str(exc))
"""
result = run_py(CAPTURE_ERROR_CODE, cwd=ROOT)
check("缺素材时报可读错误", "error True" in result.stdout, result.stdout + result.stderr)

# 窗口不存在时：calibrate 应返回 False，截屏线程应继续存活（旧的实现会标定出垃圾值）
MISSING_WINDOW_CODE = """
import time
from capture import Capture
c = Capture("__no_such_window__")
print("calibrate", c.calibrate())
c.start()
time.sleep(1.5)
print("alive", c.thread.is_alive())
print("calibrated", c.calibrated)
print("frame_none", c.frame is None)
print("warn", "找不到窗口" in "")
"""
result = run_py(MISSING_WINDOW_CODE, cwd=ROOT / "haikuScripts")
check("窗口缺失时 calibrate 返回 False", "calibrate False" in result.stdout, result.stdout + result.stderr)
check("窗口缺失时截屏线程不崩", "alive True" in result.stdout, result.stdout + result.stderr)
check("窗口缺失时保持未标定", "calibrated False" in result.stdout, result.stdout + result.stderr)
check("窗口缺失时有可读提示", "找不到窗口" in result.stdout, result.stdout + result.stderr)
check("窗口缺失时无异常堆栈", "Traceback" not in result.stdout + result.stderr, result.stdout + result.stderr)

# ---------------------------------------------------------------- 4. stop：急停与松键
print("\n[4] stop 急停与按键记账（假 pydirectinput）")
STOP_CODE = """
import sys, time, types
from maplebot import stop

calls = []
fake = types.ModuleType("pydirectinput")
def keyDown(k): calls.append(("down", k))
def keyUp(k): calls.append(("up", k))
def press(k): calls.append(("press", k))
def mouseDown(b="left"): calls.append(("mdown", b))
def mouseUp(b="left"): calls.append(("mup", b))
fake.keyDown, fake.keyUp, fake.press, fake.mouseDown, fake.mouseUp = keyDown, keyUp, press, mouseDown, mouseUp
sys.modules["pydirectinput"] = fake

import pydirectinput
stop.install(enabled=False)          # 不装 pynput 监听
pydirectinput.keyDown("f")
pydirectinput.mouseDown("left")
try:
    time.sleep(0.01)
    print("sleep_before_stop", "ok")
except stop.StopScript:
    print("sleep_before_stop", "unexpected")

stop.request_stop("unit test")
try:
    pydirectinput.keyUp("f")
    print("raise_on_key", False)
except stop.StopScript:
    print("raise_on_key", True)
try:
    time.sleep(0.5)
    print("raise_on_sleep", False)
except stop.StopScript:
    print("raise_on_sleep", True)
try:
    try:
        pydirectinput.press("g")
    except Exception:
        print("stop_swallowed_by_except_exception", True)
    else:
        print("stop_swallowed_by_except_exception", False)
except stop.StopScript:
    print("stop_swallowed_by_except_exception", False)

stop.uninstall()
print("released_key", ("up", "f") in calls)
print("released_mouse", ("mup", "left") in calls)
print("sleep_restored", time.sleep.__module__ == "time" and time.sleep.__name__ == "sleep")
time.sleep(0.01)
print("sleep_works_after", True)
print("stop_cleared", not stop.is_stopped())
"""
result = run_py(STOP_CODE, cwd=ROOT)
for expected in (
    "sleep_before_stop ok",
    "raise_on_key True",
    "raise_on_sleep True",
    "stop_swallowed_by_except_exception False",
    "released_key True",
    "released_mouse True",
    "sleep_restored True",
    "sleep_works_after True",
    "stop_cleared True",
):
    check(f"stop {expected}", expected in result.stdout, result.stdout + result.stderr)

# 关键前提：补丁必须打在「各库共享的那个 pydirectinput 模块」上，且不调用真实按键
PATCH_REACH_CODE = """
import config          # 顺带把仓库根放进 sys.path（与真实脚本一致的引导方式）
import pydirectinput
import commandBuilderLib as lib
from maplebot import stop

before = pydirectinput.keyDown
stop.install(enabled=False)
print("patched", pydirectinput.keyDown is not before)
print("same_module", lib.pydirectinput is pydirectinput)
print("lib_sees_patch", lib.pydirectinput.keyDown is pydirectinput.keyDown)
stop.uninstall()
print("restored", pydirectinput.keyDown is before)
"""
result = run_py(PATCH_REACH_CODE, cwd=ROOT / "haikuScripts")
for expected in ("patched True", "same_module True", "lib_sees_patch True", "restored True"):
    check(f"补丁可达 {expected}", expected in result.stdout, result.stdout + result.stderr)

# ---------------------------------------------------------------- 5. run.py 端到端
print("\n[5] run.py 端到端")
check("解析已有脚本", runner.resolve_script("s2_clp").name == "s2_clp.py")
check("解析 khali 脚本", runner.resolve_script("khali_library_1").name == "khali_library_1.py")
check("解析 marcoRecorder 脚本", runner.resolve_script("adele-truth1").parent.name == "marcoRecorder")
try:
    runner.resolve_script("s2_clpp")
    check("不存在的脚本应报错", False)
except SystemExit as exc:
    check("不存在的脚本给出近似建议", "s2_clp" in str(exc), str(exc))

result = run_cli("--dry-run", "--script", "s2_clp")
check("--dry-run 退出码 0", result.returncode == 0, result.stdout + result.stderr)
check("--dry-run 打印 import 检查", "import 检查" in result.stdout and "ok " in result.stdout, result.stdout + result.stderr)
check("--dry-run 能解析本地依赖", "!! " not in result.stdout, result.stdout)

result = run_cli("--dry-run", "--script", "scriptWriter")
check("--dry-run 识别出「不用截屏」的脚本", result.returncode == 0 and "不使用截屏" in result.stdout, result.stdout + result.stderr)

result = run_cli("--check")
check("--check 退出码 0", result.returncode == 0, result.stdout + result.stderr)
check("--check 报告解析数量", "解析" in result.stdout, result.stdout)

result = run_cli("--list")
check("--list 退出码 0", result.returncode == 0, result.stdout + result.stderr)
check("--list 不含库文件", "haikuScripts/capture.py" not in result.stdout, result.stdout)
check("--list 含 catms 入口", "cat_wash_cube.py" in result.stdout, result.stdout)

started = time.monotonic()
result = run_cli(
    "--script",
    "loop_forever",
    "--dir",
    "tests/fixtures",
    "--stop-after",
    "1",
    "--no-stop-key",
    timeout=60,
)
elapsed = time.monotonic() - started
check("--stop-after 能停下死循环脚本", result.returncode == 0, result.stdout + result.stderr)
check("--stop-after 有停止原因", "已停止" in result.stdout, result.stdout)
check("--stop-after 及时退出", elapsed < 30, f"{elapsed:.1f}s")
check("脚本确实跑起来过", "[fixture] started" in result.stdout, result.stdout)

# ---------------------------------------------------------------- 汇总
print()
if failures:
    print(f"FAILED ({len(failures)}): " + ", ".join(failures))
    sys.exit(1)
print("ALL PASS")
