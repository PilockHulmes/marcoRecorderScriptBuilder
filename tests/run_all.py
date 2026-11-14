"""全部测试的统一入口。

    .\\venv\\Scripts\\python.exe tests\\run_all.py

做两件事：
1. 用 unittest 跑 ``tests/test_*.py``（单元测试）；
2. 依次跑 ``tests/check_*.py``（重构自检、P0 时序自检，这两个是独立脚本）。

全部通过时退出码 0，否则 1。
"""

import subprocess
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent

CHECK_SCRIPTS = ("check_refactor.py", "check_p0_timing.py")


def run_unittest():
    loader = unittest.TestLoader()
    suite = loader.discover(str(TESTS), pattern="test_*.py", top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return result.wasSuccessful(), result.testsRun, len(result.failures) + len(result.errors)


def run_check_scripts():
    ok = True
    for name in CHECK_SCRIPTS:
        path = TESTS / name
        if not path.exists():
            print(f"[skip] {name} 不存在")
            continue
        proc = subprocess.run(
            [sys.executable, str(path)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        tail = [line for line in proc.stdout.splitlines() if line.startswith(("FAIL", "FAILED", "ALL PASS"))]
        print(f"[{'ok' if proc.returncode == 0 else 'FAIL'}] {name}: " + (" | ".join(tail[-2:]) or f"rc={proc.returncode}"))
        if proc.returncode != 0:
            ok = False
            print(proc.stdout[-3000:])
            print(proc.stderr[-3000:])
    return ok


def main():
    print("=" * 70)
    print("unittest")
    print("=" * 70)
    unit_ok, ran, bad = run_unittest()

    print()
    print("=" * 70)
    print("check scripts")
    print("=" * 70)
    check_ok = run_check_scripts()

    print()
    print("=" * 70)
    print(f"unittest: {ran} 个用例，失败 {bad} 个")
    print(f"check scripts: {'通过' if check_ok else '失败'}")
    print("总结:", "ALL PASS" if (unit_ok and check_ok) else "FAILED")
    return 0 if (unit_ok and check_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
