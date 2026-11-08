"""等待的 CPU 开销对比（P0 前后）。

    .\\venv\\Scripts\\python.exe tests\\bench_delay.py
    $env:MAPLEBOT_PRECISE_DELAY=1; .\\venv\\Scripts\\python.exe tests\\bench_delay.py   # 老行为（纯自旋）

默认（混合等待）与 ``MAPLEBOT_PRECISE_DELAY=1``（纯自旋）各跑一遍，就能看到
「等 4 秒」在 CPU 时间上的差别。用 ``time.process_time()`` 统计**本进程** CPU。
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for path in (ROOT, ROOT / "haikuScripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import commandBuilderLib as lib  # noqa: E402
from maplebot import timing  # noqa: E402

COUNT = 20
SECONDS = 0.2


def main():
    mode = "纯自旋（老行为）" if timing.PRECISE else "混合等待（P0）"
    print(f"mode={mode}  tail={timing.tail() * 1000:.2f} ms  {COUNT} × delay({SECONDS})")

    cpu0 = time.process_time()
    wall0 = time.perf_counter()
    for _ in range(COUNT):
        lib.delay(SECONDS)
    cpu_ms = (time.process_time() - cpu0) * 1000
    wall_ms = (time.perf_counter() - wall0) * 1000

    print(f"  wall = {wall_ms:8.1f} ms")
    print(f"  cpu  = {cpu_ms:8.1f} ms  ({cpu_ms / wall_ms * 100:5.1f}% 单核)")
    print(f"  avg  = {wall_ms / COUNT:8.2f} ms/次（目标 {SECONDS * 1000:.0f} ms）")


if __name__ == "__main__":
    main()
