"""看一眼时间数据积累到什么程度：哪些边/地图已经够样本，哪些还在用默认值。

    .\\venv\\Scripts\\python.exe tools\\times_report.py
"""

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maplebot import advice  # noqa: E402

RAW = ROOT / "data" / "trade" / "edge_times_raw.jsonl"
SHOP = ROOT / "data" / "trade" / "portal_shop_raw.jsonl"


def main():
    travel = advice.MapTravel()
    print(f"走路（地图级）：采信 {len(travel.times)} 条边，门级 {len(travel.portal_times)} 条")
    print(f"到商人：{len(travel.merchant_times)} 组样本\n")

    # 边样本分布
    pairs = defaultdict(list)
    if RAW.exists():
        for line in RAW.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                seconds = float(item["seconds"])
            except Exception:
                continue
            if seconds < advice.MIN_SAMPLE_SEC:
                continue
            pairs[(item["from"], item["to"])].append(seconds)

    enough = [(k, v) for k, v in pairs.items() if len(v) >= advice.MIN_SAMPLES]
    few = [(k, v) for k, v in pairs.items() if len(v) < advice.MIN_SAMPLES]
    print(f"走路样本：{len(pairs)} 条边，其中 {len(enough)} 条已采信、{len(few)} 条样本不足\n")
    print("最慢的 8 条已采信边：")
    rows = []
    for key, values in enough:
        fastest = sorted(values)[:3]
        rows.append((sum(fastest) / len(fastest), key, len(values)))
    for seconds, (a, b), n in sorted(rows, reverse=True)[:8]:
        print(f"  {seconds:6.1f}s  {a} -> {b}（{n} 条）")

    # 到商人
    if SHOP.exists():
        per = defaultdict(list)
        for line in SHOP.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if item.get("map"):
                per[item["map"]].append(float(item["seconds"]))
        print(f"\n到商人：覆盖 {len(per)} 张图，中位数最快的 6 张：")
        rows = []
        for map_name, values in per.items():
            fastest = sorted(values)[:3]
            rows.append((sum(fastest) / len(fastest), map_name, len(values)))
        for seconds, map_name, n in sorted(rows)[:6]:
            print(f"  {seconds:5.1f}s  {map_name}（{n} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
