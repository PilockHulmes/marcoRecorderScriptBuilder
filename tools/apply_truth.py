"""按"事实清单"清理过图记录里的错误边。

清单格式（data/trade/edge_truth.json）::

    {"仙人掌沙漠-3": ["豐饒的沙漠-3", "孤獨的沙漠-3"]}

含义：这张图**只**连这些邻居，其它连接一律从记录里删掉。
没写进清单的地图不受影响。

用法::

    python tools/apply_truth.py --dry     # 只看会删多少
    python tools/apply_truth.py           # 真删（先备份）
"""

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VISITS = ROOT / "data" / "trade" / "map_visits.jsonl"
TRUTH = ROOT / "data" / "trade" / "edge_truth.json"
BACKUP_DIR = ROOT / "detections" / "visits_backup"


def load_truth():
    if not TRUTH.exists():
        return {}
    data = json.loads(TRUTH.read_text(encoding="utf-8"))
    return {k: set(v) for k, v in data.items() if isinstance(v, list)}


def main(argv=None):
    dry = "--dry" in (argv or sys.argv[1:])
    truth = load_truth()
    if not truth:
        print("清单为空，无需清理")
        return 0
    if not VISITS.exists():
        print("没有记录文件")
        return 0

    lines = [l for l in VISITS.read_text(encoding="utf-8").splitlines() if l.strip()]
    kept, dropped = [], []
    for line in lines:
        event = json.loads(line)
        a, b = event.get("from_map"), event.get("to_map")
        bad = False
        for name, allowed in truth.items():
            if name in (a, b):
                other = b if a == name else a
                if other not in allowed:
                    bad = True
                    break
        (dropped if bad else kept).append(event)

    print(f"记录 {len(lines)} 条：保留 {len(kept)}，删除 {len(dropped)}")
    for event in dropped:
        print(f"  删 {event['from_map']} -> {event['to_map']}  ({event.get('t','')})")
    if dry or not dropped:
        return 0

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"map_visits_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    shutil.copy2(VISITS, backup)
    VISITS.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in kept) + "\n",
                      encoding="utf-8")
    print("已写回，备份:", backup)
    return 0


if __name__ == "__main__":
    sys.exit(main())
