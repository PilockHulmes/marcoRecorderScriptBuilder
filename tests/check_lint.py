"""静态检查：未定义的名字 / 未定义的 self 属性。

为什么要这两条（真实踩过）：

- 模块级未定义（ruff F821）：名字校验里用了从没定义过的 ``UI_WORDS``；
- 类里"只有调用没有定义"：``self._refresh_sell(...)`` 和模块级 ``_sell_line(...)``
  都曾在运行时报 NameError，而 585 个用例照样全绿——因为那条分支从没被执行，
  而且异常还被 ``except Exception`` 转成了"建议计算失败"的文字。

这两条都是**不需要运行**就能查出来的，放在说明里比写覆盖率数字更值钱。
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ["maplebot"]


def run(cmd):
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main():
    ok = True

    code, out = run([sys.executable, "-m", "ruff", "check", *TARGETS,
                     "--select", "F821,F811", "--quiet"])
    if code != 0:
        ok = False
        print("[fail] ruff: 有未定义的名字或重复定义")
        print(out.strip()[:2000])
    else:
        print("[ok] ruff: 没有未定义/重复定义的名字")

    code, out = run([sys.executable, str(ROOT / "tools" / "check_undefined.py")])
    if code != 0:
        ok = False
        print("[fail] check_undefined: 有 self 属性只调用没定义")
        print(out.strip()[-2000:])
    else:
        print("[ok] check_undefined: 所有 self 属性都有定义")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
