"""把 45 件货的"谁卖 -> 谁收"整理成一份 markdown 表格。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA = ROOT / "detections" / "routes_dump.json"
OUT = ROOT / "TRADE_ROUTES.md"

STATION_DESC = {
    1: "豐饒的沙漠-N",
    2: "孤獨的沙漠-N",
    3: "通往 X 貿易區的路",
    4: "X 貿易區-2",
    5: "X 貿易區-4",
}
NEXT = {1: 3, 3: 5, 5: 2, 2: 4, 4: 1}


def main():
    rows = json.loads(DATA.read_text(encoding="utf-8"))
    by_station = {}
    for row in rows:
        by_station.setdefault(row["station"], []).append(row)

    lines = []
    lines.append("# 跑商买卖路线全表")
    lines.append("")
    lines.append("数据来自 `data/trade/goods.json`（每个商品都记了谁卖、谁收），"
                 "共 45 件，**无一例外**符合下面的结构。")
    lines.append("")
    lines.append("## 一、五站与三条线")
    lines.append("")
    lines.append("| 站 | 地图 | 三个商人 |")
    lines.append("|---|---|---|")
    for station in sorted(by_station):
        rows_here = by_station[station]
        names = {r["line"]: f"L{r['line']} {r['seller']}" for r in rows_here}
        maps = sorted({r["seller_map"] for r in rows_here})
        lines.append(f"| 站{station} | {STATION_DESC[station]} | "
                     + " ｜ ".join(names[l] for l in sorted(names)) + " |")
    lines.append("")
    lines.append("> 具体地图：" + "；".join(
        f"站{s} = {' / '.join(sorted({r['seller_map'] for r in by_station[s]}))}"
        for s in sorted(by_station)))
    lines.append("")
    lines.append("## 二、买卖站循环")
    lines.append("")
    lines.append("```")
    lines.append("站1 豐饒 → 站3 通往路 → 站5 貿易區-4 → 站2 孤獨 → 站4 貿易區-2 → 回站1")
    lines.append("```")
    lines.append("")
    lines.append("任何一件货，**买家只在下一站**，从不在本店所在站。")
    lines.append("下一站有 3 个商人，每件货恰好被其中 **2 个**收购；"
                 "每个商人恰好收 9 件里的 **6 件**。")
    lines.append("")
    lines.append("## 三、完整对照表")
    lines.append("")
    for station in sorted(by_station):
        lines.append(f"### 站{station}（{STATION_DESC[station]}）卖的货 → 站{NEXT[station]} 收")
        lines.append("")
        lines.append("| 线 | 档位 | 商品 | 买家 1 | 买家 2 |")
        lines.append("|---|---|---|---|---|")
        for row in sorted(by_station[station], key=lambda r: (r["line"], r["tier"])):
            buyers = row["buyers"]
            cells = []
            for buyer in buyers:
                cells.append(f"{buyer['name']}（L{buyer['line']} 站{buyer['station']} "
                             f"{buyer['map']}）")
            while len(cells) < 2:
                cells.append("—")
            lines.append(f"| L{row['line']} | {row['tier']} | {row['good']} | "
                         f"{cells[0]} | {cells[1]} |")
        lines.append("")
    lines.append("## 四、按档位看线别")
    lines.append("")
    lines.append("| 档位 | 谁收 | 说明 |")
    lines.append("|---|---|---|")
    lines.append("| T1 | 另外两条线 | 永远不含卖家自己那条线 |")
    lines.append("| T2 | 本线 + 下一条线 | L1→L1/L2、L2→L2/L3、L3→L3/L1 |")
    lines.append("| T3 波动 | 多数是另外两条线 | 站2、站5 的 T3 是「本线 + 上一条线」 |")
    lines.append("")
    lines.append("## 六、更细的规律：谁会拒收哪 3 件")
    lines.append("")
    lines.append("每个买家收 9 件里的 6 件，**拒收的 3 件是有规律的**，"
                 "而且三个买家的拒收清单正好把这 9 件分光（每件恰好被一个人拒收）。")
    lines.append("")
    lines.append("记「下一条线」为 L+1（L1→L2→L3→L1），则：")
    lines.append("")
    lines.append("| 买家所在站 | 拒收的三件 |")
    lines.append("|---|---|")
    lines.append("| 站1 / 站3 / 站5 | 自己的 T1、自己的 T3、下一条线的 T2 |")
    lines.append("| 站2 / 站4 | 自己的 T1、下一条线的 T2、再下一条线的 T3 |")
    lines.append("")
    lines.append("举例（站1 的货 → 站3 的三个买家）：")
    lines.append("")
    lines.append("```")
    lines.append("道勒   (L1) 拒收 人蔘(L1T1)、傳說的精神劑(L1T3)、藍寶石碎片(L2T2)")
    lines.append("卡勒奇沙(L2) 拒收 礦石碎片(L2T1)、最上級紫水晶(L2T3)、棉(L3T2)")
    lines.append("寇比   (L3) 拒收 布塊(L3T1)、刺繡的布料(L3T3)、蜂蜜(L1T2)")
    lines.append("```")
    lines.append("")
    lines.append("三条拒收清单合起来正好是 9 件，每件只被一个人拒收。")
    lines.append("")
    lines.append("## 七、T1 / T3 的关系")
    lines.append("")
    lines.append("| 情况 | 说明 |")
    lines.append("|---|---|")
    lines.append("| 卖家在站1 / 站3 / 站4 | T1 和 T3 的买家**完全相同**（都是另外两条线） |")
    lines.append("| 卖家在站2 / 站5 | T3 多算自己那条线（本线 + 上一条线），和 T1 不同 |")
    lines.append("")
    lines.append("15 个卖家里有 9 个是「T1 买家 = T3 买家」，"
                 "另外 6 个正好是站2、站5 那两站。")
    lines.append("")
    lines.append("## 八、对工具的意义")
    lines.append("")
    lines.append("```")
    lines.append("手里有货 → 目的地固定（下一站的 2 个商人，可预先算出）")
    lines.append("不需要先看到买家出价，就知道该往哪一站走")
    lines.append("价格仍需观察：刷新是随机的，只有出价要看货架")
    lines.append("```")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("写出", OUT, "行数", len(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
