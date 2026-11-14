"""汇总每条边的跑路耗时。

优先用运行时样本（`edge_times_raw.jsonl`，不含逛商店的时间）；
没有运行时样本时，退回用过图记录推算（`map_visits.jsonl`）。

每条边只保留**最快的 10 次**，避免走神/购物污染估算。
"""

import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VISITS = ROOT / "data" / "trade" / "map_visits.jsonl"
RAW = ROOT / "data" / "trade" / "edge_times_raw.jsonl"
OUT = ROOT / "data" / "trade" / "edge_times.json"
KEEP = 3


def parse(stamp):
    try:
        return datetime.fromisoformat(stamp)
    except Exception:
        return None


def read_jsonl(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def samples_from_raw():
    samples = defaultdict(list)
    for item in read_jsonl(RAW):
        try:
            seconds = float(item["seconds"])
            pair = (item["from"], item["to"])
        except Exception:
            continue
        if 1.0 <= seconds <= 600.0:
            samples[pair].append(seconds)
    return samples


def samples_from_visits():
    events = []
    for event in read_jsonl(VISITS):
        moment = parse(event.get("t", ""))
        if moment is not None:
            events.append((moment, event))
    events.sort(key=lambda item: item[0])
    samples = defaultdict(list)
    for index in range(1, len(events)):
        previous_time, previous = events[index - 1]
        now, event = events[index]
        if previous.get("to_map") != event.get("from_map"):
            continue
        seconds = (now - previous_time).total_seconds() - (event.get("load_ms") or 0) / 1000.0
        if 1.0 <= seconds <= 600.0:
            samples[(event["from_map"], event["to_map"])].append(seconds)
    return samples


def main():
    samples = samples_from_raw()
    source = "运行时样本"
    if not samples:
        samples = samples_from_visits()
        source = "过图记录推算"

    table = []
    for (a, b), values in samples.items():
        fastest = sorted(values)[:KEEP]
        table.append({"from": a, "to": b, "n": len(values),
                      "fastest": [round(v, 1) for v in fastest],
                      "best": round(fastest[0], 1),
                      "median_fastest": round(statistics.median(fastest), 1)})
    table.sort(key=lambda r: r["median_fastest"])

    print(f"来源：{source}　可估时的边 {len(table)} 条（每条取最快 {KEEP} 次）\n")
    for row in table[:20]:
        print(f"  {row['median_fastest']:6.1f}s  最快{row['best']:5.1f}s  样本{row['n']:3}  "
              f"{row['from']} → {row['to']}")

    OUT.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nsaved", OUT)


if __name__ == "__main__":
    sys.exit(main())
