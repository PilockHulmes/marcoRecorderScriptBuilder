"""按"商店列表顺序"重算商品类别。

规则（用户确认）：
  每个商人卖给我的列表中，第 1 个 = 一类，第 2 个 = 二类，
  如果存在第 3 个可买商品，它就是波动商品。

观察记录里的 rows 保持了屏幕顺序，所以直接按出现次序投票即可。
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OBS = ROOT / "data" / "trade" / "observations.jsonl"
GOODS = ROOT / "data" / "trade" / "goods.json"

ORDER_TIER = ["tier1", "tier2", "volatile"]


def main():
    goods = json.loads(GOODS.read_text(encoding="utf-8"))
    by_id = {g["id"]: g for g in goods["goods"]}

    votes = defaultdict(Counter)
    if OBS.exists():
        for line in OBS.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                observation = json.loads(line)
            except Exception:
                continue
            sells = [row for row in observation.get("rows", []) if row.get("side") == "sell"]
            for index, row in enumerate(sells[:3]):
                good_id = row.get("good_id")
                if good_id in by_id:
                    votes[good_id][ORDER_TIER[index]] += 1

    changes = []
    for good_id, counter in votes.items():
        if not counter:
            continue
        best = counter.most_common(1)[0][0]
        good = by_id[good_id]
        if good.get("tier") != best:
            changes.append((good["name"], good.get("tier"), best, dict(counter)))
            good["tier"] = best

    GOODS.write_text(json.dumps(goods, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"按商店顺序投票：{len(votes)} 个商品有证据，改动 {len(changes)} 个\n")
    for name, old, new, detail in changes:
        print(f"  {name:10} {old} -> {new}   {detail}")


if __name__ == "__main__":
    sys.exit(main())
