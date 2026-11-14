"""从 map_visits.jsonl 离线估算每条边的跑路耗时。

每条过图事件的 t 是"到达新图"的时刻，所以：

    这一次的耗时 ≈ (本事件 t - 上一条事件 t) - loading

这段时间里包含"在上一张图里走到传送门"的时间（也包含可能开了商人界面的时间），
所以按用户要求只保留**最快的 10 次**，避免走神/购物污染估算。
"""

import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VISITS = ROOT / "data" / "trade" / "map_visits.jsonl"
OUT = ROOT / "data" / "trade" / "edge_times.json"
KEEP = 10


def parse(stamp):
    try:
        return datetime.fromisoformat(stamp)
    except Exception:
        return None


def main():
    events = []
    for line in VISITS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        moment = parse(event.get("t", ""))
        if moment is not None:
            events.append((moment, event))
    events.sort(key=lambda item: item[0])

    samples = defaultdict(list)
    for index in range(1, len(events)):
        previous_time, previous = events[index - 1]
        now, event = events[index]
        if previous["to_map"] != event["from_map"]:
            continue                      # 中间断过，不可比
        seconds = (now - previous_time).total_seconds() - (event.get("load_ms") or 0) / 1000.0
        if 1.0 <= seconds <= 600.0:
            samples[(event["from_map"], event["to_map"])].append(seconds)

    table = []
    for (a, b), values in samples.items():
        fastest = sorted(values)[:KEEP]
        table.append({
            "from": a, "to": b, "n": len(values),
            "fastest": [round(v, 1) for v in fastest],
            "best": round(fastest[0], 1),
            "median_fastest": round(statistics.median(fastest), 1),
        })
    table.sort(key=lambda r: r["median_fastest"])

    print(f"可估时的边 {len(table)} 条（每条取最快 {KEEP} 次）\n")
    for row in table[:20]:
        print(f"  {row['median_fastest']:6.1f}s  最快{row['best']:5.1f}s  样本{row['n']:3}  "
              f"{row['from']} → {row['to']}")

    OUT.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nsaved", OUT)


if __name__ == "__main__":
    main()
