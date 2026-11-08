"""P0 回归测试：等待是否既准又不烧 CPU。

运行：``.\\venv\\Scripts\\python.exe tests\\test_p0_timing.py``

判定标准：
- **不早于 deadline**（精度不能回退，否则动作时序会变）；
- 长等待（>= 100 ms）的 CPU 时间必须远小于墙钟时间（原来 1:1 烧满一个核）；
- ``MAPLEBOT_PRECISE_DELAY=1`` 能退回纯自旋（老行为）。
"""

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}

sys.path.insert(0, str(ROOT))
from maplebot import timing  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok or not detail else f"\n      {detail}"))
    if not ok:
        failures.append(name)


def measure(fn):
    """返回 (墙钟 ms, 本进程 CPU ms)。"""
    cpu0 = time.process_time()
    wall0 = time.perf_counter()
    fn()
    return (time.perf_counter() - wall0) * 1000, (time.process_time() - cpu0) * 1000


def run_py(code, cwd=ROOT, env=None, timeout=60):
    return subprocess.run(
        [PY, "-c", code],
        cwd=str(cwd),
        env={**ENV, **(env or {})},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


# ---------------------------------------------------------------- 1. 精度
print("\n[1] 精度：不早于 deadline")
early = 0
worst = 0.0
for _ in range(30):
    wall, _cpu = measure(lambda: timing.sleep_precise(0.01))
    if wall < 9.5:
        early += 1
    worst = max(worst, wall)
check("30 次 10ms 等待没有提前返回", early == 0, f"提前 {early} 次，最长 {worst:.2f} ms")
check("10ms 等待不会明显超时", worst < 40, f"最长 {worst:.2f} ms")

wall, _ = measure(lambda: timing.sleep_precise(0.0))
check("sleep_precise(0) 立即返回", wall < 2, f"{wall:.2f} ms")

wall, _ = measure(lambda: timing.sleep_precise(-1))
check("sleep_precise(负数) 立即返回", wall < 2, f"{wall:.2f} ms")

# 15ms 是 INTERVAL_CLICK：刚好比自旋尾段长一点点，必须仍然准（不能因为 sleep 过冲变长）
short_walls = [measure(lambda: timing.sleep_precise(0.015))[0] for _ in range(20)]
short_avg = sum(short_walls) / len(short_walls)
check("15ms 等待平均值贴近目标", 14.5 <= short_avg <= 16.5, f"平均 {short_avg:.2f} ms")
check("15ms 等待最大值不超 25ms", max(short_walls) < 25, f"最大 {max(short_walls):.2f} ms")

# ---------------------------------------------------------------- 2. CPU 占用
print("\n[2] 长等待的 CPU 占用")
print(f"     自旋尾段 tail = {timing.tail() * 1000:.2f} ms")

wall, cpu = measure(lambda: timing.sleep_precise(0.25))
check("250ms 等待墙钟正确", 245 <= wall <= 450, f"{wall:.1f} ms")
check("250ms 等待 CPU < 60ms（原先约 250ms）", cpu < 60, f"CPU {cpu:.1f} ms")
check("250ms 等待 CPU < 墙钟的 30%", cpu < wall * 0.3, f"CPU {cpu:.1f} / wall {wall:.1f} ms")

total_wall = total_cpu = 0.0
for _ in range(10):
    w, c = measure(lambda: timing.sleep_precise(0.1))
    total_wall += w
    total_cpu += c
check(
    "连续 10 次 100ms 等待的总 CPU 占比 < 30%",
    total_cpu < total_wall * 0.3,
    f"CPU {total_cpu:.1f} ms / wall {total_wall:.1f} ms",
)

# ---------------------------------------------------------------- 3. 集成：commandBuilderLib.delay
print("\n[3] commandBuilderLib.delay / delayRandomly")
DELAY_CODE = """
import time
import commandBuilderLib as lib

def measure(fn):
    c0 = time.process_time(); w0 = time.perf_counter()
    fn()
    return (time.perf_counter() - w0) * 1000, (time.process_time() - c0) * 1000

w, c = measure(lambda: lib.delay(0.2))
print(f"delay200_wall={w:.1f} delay200_cpu={c:.1f}")
w2, c2 = measure(lambda: lib.delay(0.0))
print(f"delay0_wall={w2:.2f} delay0_cpu={c2:.2f}")
w3, c3 = measure(lambda: lib.delayRandomly(0.05))
print(f"delayrand_wall={w3:.1f} delayrand_cpu={c3:.1f}")
"""
result = run_py(DELAY_CODE, cwd=ROOT / "haikuScripts")
print("     " + " | ".join(result.stdout.split()))
check("commandBuilderLib 可导入并执行", "delay200_wall=" in result.stdout, result.stdout + result.stderr)

if "delay200_wall=" in result.stdout:
    parts = dict(item.split("=") for item in result.stdout.split() if "=" in item)
    delay_wall = float(parts["delay200_wall"])
    delay_cpu = float(parts["delay200_cpu"])
    check("lib.delay(0.2) 墙钟正确", 195 <= delay_wall <= 450, f"{delay_wall} ms")
    check("lib.delay(0.2) CPU < 60ms（原先约 200ms）", delay_cpu < 60, f"{delay_cpu} ms")
    check("lib.delay(0) 立即返回", float(parts["delay0_wall"]) < 2, result.stdout)
    check(
        "lib.delayRandomly(0.05) 含抖动但不超上限",
        50 <= float(parts["delayrand_wall"]) <= 50 + 70 + 50,
        result.stdout,
    )

# ---------------------------------------------------------------- 4. 逃生开关
print("\n[4] MAPLEBOT_PRECISE_DELAY=1 退回纯自旋")
PRECISE_CODE = """
import time
from maplebot import timing
print("tail", timing.tail())
c0 = time.process_time(); w0 = time.perf_counter()
timing.sleep_precise(0.1)
print("cpu", round((time.process_time() - c0) * 1000))
print("wall", round((time.perf_counter() - w0) * 1000))
"""
result = run_py(PRECISE_CODE, env={"MAPLEBOT_PRECISE_DELAY": "1"})
print("     " + " | ".join(result.stdout.split()))
check("逃生开关生效（tail=0）", "tail 0.0" in result.stdout, result.stdout + result.stderr)
if "cpu " in result.stdout and "wall " in result.stdout:
    precise_cpu = float(result.stdout.split("cpu ")[1].split()[0])
    precise_wall = float(result.stdout.split("wall ")[1].split()[0])
    check(
        "逃生开关下 CPU 回到纯自旋（>= 墙钟 80%）",
        precise_cpu >= precise_wall * 0.8,
        f"CPU {precise_cpu} ms / wall {precise_wall} ms",
    )

# ---------------------------------------------------------------- 5. 帧间隔可调
print("\n[5] Capture.set_frame_interval")
FRAME_CODE = """
from capture import Capture
c = Capture("__no_such_window__")
print("default", c.frame_interval)
print("set", c.set_frame_interval(0.33))
print("now", c.frame_interval)
try:
    c.set_frame_interval(0)
    print("zero_rejected", False)
except ValueError:
    print("zero_rejected", True)
"""
result = run_py(FRAME_CODE, cwd=ROOT / "haikuScripts")
for expected in ("default 0.1", "set 0.33", "now 0.33", "zero_rejected True"):
    check(f"set_frame_interval {expected}", expected in result.stdout, result.stdout + result.stderr)

# ---------------------------------------------------------------- 汇总
print()
if failures:
    print(f"FAILED ({len(failures)}): " + ", ".join(failures))
    sys.exit(1)
print("ALL PASS")
