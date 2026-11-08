#!/usr/bin/env python
"""统一入口。

    python run.py --list
    python run.py --script s2_clp --window "MapleStory" --wait 60

实现在 `maplebot/runner.py`，这里只做 `sys.path` 引导，方便从任意目录调用。
"""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from maplebot.runner import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
