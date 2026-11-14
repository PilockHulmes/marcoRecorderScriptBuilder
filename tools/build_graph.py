"""按用户口述的线路结构建立"真实地图图"，并和记录比对。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CHAINS = [
    ["貿易地帶岔道", "豐饒的沙漠-1", "仙人掌沙漠-1", "孤獨的沙漠-1", "寂寞的沙漠-1"],
    ["貿易地帶岔道", "豐饒的沙漠-2", "仙人掌沙漠-2", "孤獨的沙漠-2", "寂寞的沙漠-2"],
    ["貿易地帶岔道", "豐饒的沙漠-3", "仙人掌沙漠-3", "孤獨的沙漠-3", "寂寞的沙漠-3"],
    ["寂寞的沙漠-3", "通往古代遺跡的路", "古代遺跡地內部-1", "古代遺跡地內部-2",
     "古代遺跡地內部-3", "古代遺跡地內部-4"],
]

edges = set()
for chain in CHAINS:
    for a, b in zip(chain, chain[1:]):
        edges.add(tuple(sorted((a, b))))
# 起点列车
edges.add(tuple(sorted(("休菲凱曼的探險列車", "貿易地帶岔道"))))

graph = {}
for a, b in edges:
    graph.setdefault(a, set()).add(b)
    graph.setdefault(b, set()).add(a)

out = ROOT / "data" / "trade" / "map_graph_user.json"
out.parent.mkdir(parents=True, exist_ok=True)
data = {"source": "用户口述", "edges": [list(e) for e in sorted(edges)]}
out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"真实图：{len(graph)} 个地图，{len(edges)} 条连接")
for name in sorted(graph):
    print(f"  {name:20} {len(graph[name])}  {sorted(graph[name])}")

from maplebot import mapwatch  # noqa: E402

visits = mapwatch.MapWatcher().load_visits()
recorded = set()
for e in visits:
    a, b = e.get("from_map"), e.get("to_map")
    if a and b and a != b:
        recorded.add(tuple(sorted((a, b))))

print("\n--- 记录里没有、但真实存在的连接 ---")
for a, b in sorted(edges - recorded):
    print(f"  {a} <-> {b}")
print("\n--- 记录里有、但真实不存在的连接 ---")
for a, b in sorted(recorded - edges):
    if a in graph or b in graph:
        print(f"  {a} <-> {b}")
