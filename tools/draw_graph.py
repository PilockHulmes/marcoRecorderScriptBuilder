"""把地图连接图画成缩进树（起点：休菲凱曼的探險列車），并标出两个环。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GRAPH = ROOT / "data" / "trade" / "map_graph.json"
OUT = ROOT / "data" / "trade" / "map_tree.md"

# 想让输出符合线路走向：邻居按这个顺序排
ORDER = {
    "貿易地帶岔道": ["豐饒的沙漠-1", "豐饒的沙漠-2", "豐饒的沙漠-3", "休菲凱曼的探險列車"],
    "寂寞的沙漠-1": ["孤獨的沙漠-1", "寂寞的沙漠捷徑-1", "寂寞的沙漠捷徑-3", "通往納希貿易區的路"],
    "寂寞的沙漠-2": ["孤獨的沙漠-2", "寂寞的沙漠捷徑-1", "寂寞的沙漠捷徑-2", "通往瑪迦提亞貿易區的路"],
    "寂寞的沙漠-3": ["孤獨的沙漠-3", "寂寞的沙漠捷徑-2", "寂寞的沙漠捷徑-3", "通往古代遺跡的路"],
    "納希貿易區-3": ["納希貿易區-2", "納希貿易區-4", "地下捷徑-1", "地下捷徑-3"],
    "瑪迦提亞貿易區-3": ["瑪迦提亞貿易區-2", "瑪迦提亞貿易區-4", "地下捷徑-1", "地下捷徑-2"],
    "古代遺跡地內部-3": ["古代遺跡地內部-2", "古代遺跡地內部-4", "地下捷徑-2", "地下捷徑-3"],
}


def main():
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    lines = []
    seen = set()

    def walk(node, depth, via):
        pad = "\t" * depth
        if node in seen:
            lines.append(f"{pad}↩ {node}（已在上方出现{via}）")
            return
        seen.add(node)
        lines.append(f"{pad}{node}")
        neighbours = ORDER.get(node) or sorted(graph.get(node, []))
        for nxt in neighbours:
            if nxt in seen:
                lines.append("\t" * (depth + 1) + f"↩ {nxt}（已在上方出现）")
            else:
                walk(nxt, depth + 1, "")

    walk("休菲凱曼的探險列車", 0, "")
    body = "\n".join(lines)

    rings = """

## 两个环

### 环一：寂寞的沙漠 + 沙漠捷徑

    寂寞的沙漠-1 -- 寂寞的沙漠捷徑-1 -- 寂寞的沙漠-2
         |                                    |
    寂寞的沙漠捷徑-3 -- 寂寞的沙漠-3 -- 寂寞的沙漠捷徑-2

（三条「沙漠捷徑」把三个「寂寞的沙漠」连成三角环）

### 环二：地下捷徑

    納希貿易區-3 -- 地下捷徑-1 -- 瑪迦提亞貿易區-3
         |                              |
    地下捷徑-3 -- 古代遺跡地內部-3 -- 地下捷徑-2

（三条「地下捷徑」把三个 4 度枢纽连成三角环）
"""
    text = "# 跑商地图连接图\n\n起点：休菲凱曼的探險列車\n\n```\n" + body + "\n```\n" + rings
    OUT.write_text(text, encoding="utf-8")
    print(body)
    print("\nsaved", OUT)


if __name__ == "__main__":
    main()
