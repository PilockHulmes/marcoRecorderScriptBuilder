"""清掉记录里"不可能"的商店刷新时间（把 03:00 读成 30:00 那批）。

商店刷新是 3~5 分钟（180~300 秒），所以 refresh_in > 360 一定读错了。
"""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "trade" / "observations.jsonl"
BACKUP = PATH.with_suffix(".jsonl.bak")
LIMIT = 360


def main():
    if not PATH.exists():
        print("没有记录文件")
        return 1
    lines = PATH.read_text(encoding="utf-8").splitlines()
    kept, dropped = [], 0
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        refresh = row.get("refresh_in") or 0
        if refresh > LIMIT:
            dropped += 1
            continue
        kept.append(line)

    shutil.copy2(PATH, BACKUP)
    PATH.write_text("\n".join(kept) + "\n", encoding="utf-8")
    print(f"备份: {BACKUP.name}")
    print(f"删除 {dropped} 条 refresh_in > {LIMIT} 秒的记录，保留 {len(kept)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
