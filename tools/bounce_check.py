"""检查跑图样本里有多少是"从同一个门进去又立刻出来"（穿门折返）。

判断依据：这一条的出发位置，和上一条的到达位置相同（同一个传送门），
说明玩家进门之后马上又从这个门出去了，中间根本没走图。
"""

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "trade" / "edge_times_raw.jsonl"


def same_portal(a, b, tol=0.05):
    if not a or not b:
        return False
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def main():
    rows = [json.loads(line) for line in RAW.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    print(f"样本 {len(rows)} 条\n")

    bounce, short, both = 0, 0, 0
    for index in range(1, len(rows)):
        previous, current = rows[index - 1], rows[index]
        escaped = current["from"] != previous["to"]
        if escaped:
            continue                          # 中间换过图，不能这么比
        is_bounce = same_portal(current.get("from_portal"), previous.get("to_portal"))
        is_short = current["seconds"] < 3.0
        bounce += is_bounce
        short += is_short
        both += is_bounce and is_short

    print(f"与上一条首尾相接的样本里：")
    print(f"  出发门 == 上一条到达门（原路折返）: {bounce} 条")
    print(f"  耗时 < 3 秒                        : {short} 条")
    print(f"  两者都满足                          : {both} 条")

    quick = Counter()
    for row in rows:
        if row["seconds"] < 2.0:
            quick[(row["from"], row["to"])] += 1
    print(f"\n耗时 < 2 秒的边（前 8）：")
    for (a, b), n in quick.most_common(8):
        print(f"  {a} -> {b}: {n} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
