"""用地图图 + 商人所在地图 + 买卖表，算商路距离（按经过的地图数）。"""

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load(name):
    return json.loads((ROOT / "data" / "trade" / name).read_text(encoding="utf-8"))


def main():
    graph = load("map_graph.json")
    merchant_maps = load("merchant_maps.json")
    goods = load("goods.json")

    where = {}          # 知识库商人 id -> 地图
    for key, item in merchant_maps.items():
        where[item["merchant_id"]] = item["map"]

    # BFS：任意两图之间的跳数
    def hops(src):
        dist = {src: 0}
        queue = collections.deque([src])
        while queue:
            node = queue.popleft()
            for nxt in graph.get(node, []):
                if nxt not in dist:
                    dist[nxt] = dist[node] + 1
                    queue.append(nxt)
        return dist

    merchants = {m["id"]: m for m in goods["merchants"]}
    by_good = {g["id"]: g for g in goods["goods"]}

    table = []
    for good in goods["goods"]:
        seller = good.get("seller")
        s_map = where.get(seller)
        if not s_map:
            continue
        dist = hops(s_map)
        for buyer in good.get("buyers", []):
            b_map = where.get(buyer)
            if not b_map or b_map not in dist:
                continue
            table.append({
                "good": good["name"],
                "tier": good.get("tier"),
                "from_merchant": merchants.get(seller, {}).get("name", seller),
                "from_map": s_map,
                "to_merchant": merchants.get(buyer, {}).get("name", buyer),
                "to_map": b_map,
                "hops": dist[b_map],
            })

    table.sort(key=lambda r: (r["hops"], r["good"]))
    print(f"可计算的商路 {len(table)} 条（按经过地图数排序）\n")
    for row in table[:25]:
        print(f"  {row['hops']} 张图  {row['tier']:8} {row['good']:8}  "
              f"{row['from_merchant']}({row['from_map']})  →  "
              f"{row['to_merchant']}({row['to_map']})")

    out = ROOT / "data" / "trade" / "goods_routes.json"
    out.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nsaved", out)


if __name__ == "__main__":
    main()
