"""跑商买卖关系图。

把 ``data/trade/goods.json`` 里的两份平铺数据（``merchants[]`` / ``goods[]``）
变成可双向查询的图：

- 商品 → 谁卖 / 谁收（:meth:`TradeGraph.sellers` / :meth:`buyers`）；
- 商人 → 卖什么 / 收什么（:meth:`TradeGraph.sells` / :meth:`buys`）；
- 商人 → 在这里买货能去哪卖（:meth:`TradeGraph.opportunities`）；
- 商人 → 我收的货该去哪买（:meth:`TradeGraph.reverse_opportunities`）；
- 商人 → 两跳路线（:meth:`TradeGraph.routes_from`）。

数据模型有两个刻意的不对称，别把它当 bug：

1. ``merchants[].sells`` 只列 **2 种普通货**；波动商品（``tier == "volatile"``）
   由 ``goods[].seller`` 指向商人，但不出现在 ``sells`` 里（因此每个商人的
   ``goods[].seller`` 实际是 2 普通 + 1 波动 = 3 种）。
2. 同理 ``merchants[].buys`` 只列 **4 种普通回收货**；波动商品的回收关系只在
   ``goods[].buyers`` 里，所以按 ``goods[].buyers`` 反查，每个商人会收 6 种。

查询按 id 或中文名都行；中文名 ``人蔘`` 是攻略里的写法，知识库写作 ``山参``，
这里做了个别名兼容（见 :data:`GOOD_ALIASES`），未知 key 仍然抛 ``KeyError``。

命令行::

    python -m maplebot.trade_graph --good 人蔘
    python -m maplebot.trade_graph --merchant kobi_1
    python -m maplebot.trade_graph --from kobi_1
    python -m maplebot.trade_graph --validate
    python -m maplebot.trade_graph --stats
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

#: 知识库默认路径（相对仓库根，不依赖当前工作目录）。
DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "trade" / "goods.json"

#: ``line`` 字段的合法取值。
VALID_LINES = ("kobi", "dour", "ore")

#: 攻略/任务里常用的异名 → 知识库中文名。
#: 只做查询兼容，不写回数据；未列出的 key 仍然抛 ``KeyError``。
GOOD_ALIASES = {
    "人蔘": "山参",
    "人参": "山参",
}


class TradeGraph:
    """买卖关系图。

    :param path: 知识库 JSON 路径；默认 ``data/trade/goods.json``。
                 显式传入时相对路径按当前工作目录解析。
    """

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else DEFAULT_PATH
        # 这台机器的 Python 默认用 GBK 打开文本文件，必须显式指定 UTF-8。
        with self.path.open("r", encoding="utf-8") as fh:
            self.data = json.load(fh)

        if not isinstance(self.data, dict):
            raise ValueError(f"知识库顶层应为对象: {self.path}")
        merchants = self.data.get("merchants")
        goods = self.data.get("goods")
        if not isinstance(merchants, list) or not isinstance(goods, list):
            raise ValueError(f"知识库缺少 merchants[] 或 goods[]: {self.path}")

        self.merchants = merchants
        self.goods = goods
        self._merchants_by_id = {
            m["id"]: m
            for m in merchants
            if isinstance(m, dict) and isinstance(m.get("id"), str) and m["id"]
        }
        self._merchants_by_name = {
            m["name"]: m
            for m in merchants
            if isinstance(m, dict) and isinstance(m.get("name"), str) and m["name"]
        }
        self._goods_by_id = {
            g["id"]: g
            for g in goods
            if isinstance(g, dict) and isinstance(g.get("id"), str) and g["id"]
        }
        self._goods_by_name = {
            g["name"]: g
            for g in goods
            if isinstance(g, dict) and isinstance(g.get("name"), str) and g["name"]
        }

    # ------------------------------------------------------------ 基础查询

    def good(self, key):
        """按 id 或中文名查商品；找不到抛 ``KeyError``。"""
        if isinstance(key, dict):
            gid = key.get("id")
            if isinstance(gid, str) and gid in self._goods_by_id:
                return self._goods_by_id[gid]
            key = key.get("name")
        if isinstance(key, str):
            key = GOOD_ALIASES.get(key, key)
            if key in self._goods_by_id:
                return self._goods_by_id[key]
            if key in self._goods_by_name:
                return self._goods_by_name[key]
        raise KeyError(f"未知商品: {key!r}（可用 id 或中文名）")

    def merchant(self, key):
        """按 id 或中文名查商人；找不到抛 ``KeyError``。"""
        if isinstance(key, dict):
            mid = key.get("id")
            if isinstance(mid, str) and mid in self._merchants_by_id:
                return self._merchants_by_id[mid]
            key = key.get("name")
        if isinstance(key, str):
            if key in self._merchants_by_id:
                return self._merchants_by_id[key]
            if key in self._merchants_by_name:
                return self._merchants_by_name[key]
        raise KeyError(f"未知商人: {key!r}（可用 id 或中文名）")

    def sellers(self, good):
        """谁卖这个商品（普通货/波动货都按 ``goods[].seller``，通常 1 个）。"""
        g = self._as_good(good)
        seller_id = g.get("seller")
        seller = (
            self._merchants_by_id.get(seller_id)
            if isinstance(seller_id, str)
            else None
        )
        return [seller] if seller is not None else []

    def buyers(self, good):
        """谁收这个商品（通常 2 个，按数据里的顺序）。"""
        g = self._as_good(good)
        buyer_ids = g.get("buyers")
        if not isinstance(buyer_ids, list):
            return []
        out = []
        for buyer_id in buyer_ids:
            buyer = (
                self._merchants_by_id.get(buyer_id)
                if isinstance(buyer_id, str)
                else None
            )
            if buyer is not None:
                out.append(buyer)
        return out

    def sells(self, merchant):
        """这个商人卖哪 2 种普通货（按 ``merchants[].sells`` 顺序）。"""
        m = self._as_merchant(merchant)
        return [self.good(name) for name in m.get("sells") or []]

    def buys(self, merchant):
        """这个商人收哪 4 种普通货（按 ``merchants[].buys`` 顺序）。"""
        m = self._as_merchant(merchant)
        return [self.good(name) for name in m.get("buys") or []]

    # ------------------------------------------------------------ 派生查询

    def opportunities(self, merchant):
        """站在这个商人这里，能买到的普通货 → 每个货的买家列表 + 线路。

        返回 ``[{"good": {...}, "buyers": [{...}], "line": "kobi",
        "same_line_buyer": True/False}, ...]``。

        ``same_line_buyer`` 表示该商品的买家里是否有和当前商人同一条线的人
        （同线通常更省跑图时间）。
        """
        m = self._as_merchant(merchant)
        line = m.get("line")
        result = []
        for g in self.sells(m):
            buyers = self.buyers(g)
            result.append(
                {
                    "good": g,
                    "buyers": buyers,
                    "line": line,
                    "same_line_buyer": any(b.get("line") == line for b in buyers),
                }
            )
        return result

    def reverse_opportunities(self, merchant):
        """这个商人收的普通货 → 谁会卖这些货（"我手上没有，可以去哪买"）。

        返回 ``[{"good": {...}, "sellers": [{...}], "line": "kobi",
        "same_line_seller": True/False}, ...]``。
        """
        m = self._as_merchant(merchant)
        line = m.get("line")
        result = []
        for g in self.buys(m):
            sellers = self.sellers(g)
            result.append(
                {
                    "good": g,
                    "sellers": sellers,
                    "line": line,
                    "same_line_seller": any(s.get("line") == line for s in sellers),
                }
            )
        return result

    def routes_from(self, merchant):
        """从当前商人出发的两跳路线（只做一跳 + 一跳，不做全图搜索）。

        第一跳：买这里卖的普通货，去它的某个买家卖掉；
        第二跳：看看这个买家那里又能买什么（``next_goods``）。

        返回 ``[{"from": {...}, "good": {...}, "buyer": {...},
        "line": "kobi", "same_line": True/False, "next_goods": [{...}]}, ...]``。
        每个 (在售货, 买家) 组合一条，不递归、不剪枝、不搜索全图。
        """
        m = self._as_merchant(merchant)
        line = m.get("line")
        result = []
        for g in self.sells(m):
            for buyer in self.buyers(g):
                result.append(
                    {
                        "from": m,
                        "good": g,
                        "buyer": buyer,
                        "line": buyer.get("line"),
                        "same_line": buyer.get("line") == line,
                        "next_goods": self.sells(buyer),
                    }
                )
        return result

    # ------------------------------------------------------------ 自检 / 统计

    def validate(self):
        """一致性检查；返回问题列表，空列表表示通过。

        至少检查：

        - 每个商品恰好 1 卖家、2 买家；
        - 每个商人 ``sells`` = 2、``buys`` = 4；
        - 所有引用（商人卖/收的商品名、商品的卖/买商人 id）都存在；
        - 商品 id 唯一、商人 id 唯一（中文名也要求唯一，否则按名查询有歧义）；
        - ``line`` 只能是 kobi / dour / ore。

        额外检查普通货的买卖关系是否双向一致；波动商品按数据模型只走
        ``goods[].seller`` / ``goods[].buyers``，不要求出现在商人的
        ``sells`` / ``buys`` 列表里。
        """
        issues = []
        data = self.data
        merchants = data.get("merchants")
        goods = data.get("goods")

        if not isinstance(merchants, list):
            issues.append("merchants 必须是数组")
            merchants = []
        if not isinstance(goods, list):
            issues.append("goods 必须是数组")
            goods = []

        price_tiers = data.get("price_tiers")
        valid_tiers = set(price_tiers) if isinstance(price_tiers, dict) else set()

        # ---- 商人：id/name 唯一、line 合法、sells=2 / buys=4
        merchant_by_id = {}
        merchant_by_name = {}
        for i, m in enumerate(merchants):
            if not isinstance(m, dict):
                issues.append(f"merchants[{i}] 不是对象")
                continue
            mid = m.get("id")
            label = mid if isinstance(mid, str) and mid else f"merchants[{i}]"
            if not isinstance(mid, str) or not mid:
                issues.append(f"{label} 缺少 id")
            elif mid in merchant_by_id:
                issues.append(f"商人 id 重复: {mid}")
            else:
                merchant_by_id[mid] = m
            name = m.get("name")
            if not isinstance(name, str) or not name:
                issues.append(f"{label} 缺少中文名")
            elif name in merchant_by_name:
                issues.append(f"商人中文名重复: {name}")
            else:
                merchant_by_name[name] = m
            line = m.get("line")
            if line not in VALID_LINES:
                issues.append(f"商人 {label} 的 line 非法: {line!r}")
            for field, expected in (("sells", 2), ("buys", 4)):
                refs = m.get(field)
                if not isinstance(refs, list):
                    issues.append(f"商人 {label} 的 {field} 不是数组")
                    continue
                if len(refs) != expected:
                    issues.append(
                        f"商人 {label} 的 {field} 应为 {expected} 种，实际 {len(refs)}"
                    )
                if not all(isinstance(ref, str) for ref in refs):
                    issues.append(f"商人 {label} 的 {field} 含非字符串项")
                elif len(refs) != len(set(refs)):
                    issues.append(f"商人 {label} 的 {field} 有重复项")

        # ---- 商品：id/name 唯一、tier 合法、1 卖家 / 2 买家、引用存在
        good_by_id = {}
        good_by_name = {}
        for i, g in enumerate(goods):
            if not isinstance(g, dict):
                issues.append(f"goods[{i}] 不是对象")
                continue
            gid = g.get("id")
            label = gid if isinstance(gid, str) and gid else f"goods[{i}]"
            if not isinstance(gid, str) or not gid:
                issues.append(f"{label} 缺少 id")
            elif gid in good_by_id:
                issues.append(f"商品 id 重复: {gid}")
            else:
                good_by_id[gid] = g
            name = g.get("name")
            if not isinstance(name, str) or not name:
                issues.append(f"{label} 缺少中文名")
            elif name in good_by_name:
                issues.append(f"商品中文名重复: {name}")
            else:
                good_by_name[name] = g

            tier = g.get("tier")
            if not isinstance(tier, str) or not tier:
                issues.append(f"商品 {label} 缺少 tier")
            elif valid_tiers and tier not in valid_tiers:
                issues.append(f"商品 {label} 的 tier 不在 price_tiers 中: {tier!r}")

            seller_id = g.get("seller")
            if not isinstance(seller_id, str) or seller_id not in merchant_by_id:
                issues.append(f"商品 {label} 的 seller 不存在: {seller_id!r}")
            buyers = g.get("buyers")
            if not isinstance(buyers, list):
                issues.append(f"商品 {label} 的 buyers 不是数组")
            else:
                if len(buyers) != 2:
                    issues.append(
                        f"商品 {label} 应有 2 个买家，实际 {len(buyers)}"
                    )
                if not all(isinstance(buyer_id, str) for buyer_id in buyers):
                    issues.append(f"商品 {label} 的 buyers 含非字符串项")
                elif len(buyers) != len(set(buyers)):
                    issues.append(f"商品 {label} 的 buyers 有重复项")
                for buyer_id in buyers:
                    if not isinstance(buyer_id, str) or buyer_id not in merchant_by_id:
                        issues.append(
                            f"商品 {label} 的 buyer 不存在: {buyer_id!r}"
                        )

        # ---- 商人 sells/buys 里的商品名必须存在，且普通货的买卖要双向一致
        for m in merchants:
            if not isinstance(m, dict):
                continue
            mid = m.get("id")
            label = mid if isinstance(mid, str) and mid else "?"
            for field in ("sells", "buys"):
                refs = m.get(field)
                if not isinstance(refs, list):
                    continue
                for ref_name in refs:
                    g = good_by_name.get(ref_name) if isinstance(ref_name, str) else None
                    if g is None:
                        issues.append(
                            f"商人 {label} 的 {field} 引用不存在的商品: {ref_name!r}"
                        )
                        continue
                    buyers = g.get("buyers")
                    if (
                        field == "buys"
                        and isinstance(buyers, list)
                        and mid not in buyers
                    ):
                        issues.append(
                            f"商人 {label} 收 {ref_name}，但该商品的 buyers 不含他"
                        )

        # ---- 每个商品恰好 1 个卖家：普通货必须恰好挂在 1 个商人的 sells 里；
        #      波动商品不在 sells 里，只由 goods[].seller 指向唯一卖家。
        for g in goods:
            if not isinstance(g, dict):
                continue
            name = g.get("name")
            gid = g.get("id")
            label = gid if isinstance(gid, str) and gid else name
            tier = g.get("tier")
            seller_id = g.get("seller")
            listings = [
                m
                for m in merchants
                if isinstance(m, dict)
                and isinstance(m.get("sells"), list)
                and name in m["sells"]
            ]
            if tier == "volatile":
                if listings:
                    issues.append(
                        f"波动商品 {label} 不应出现在 merchants[].sells 中"
                    )
            else:
                if len(listings) != 1:
                    issues.append(
                        f"商品 {label} 应恰好有 1 个卖家，实际 {len(listings)}"
                    )
                elif listings[0].get("id") != seller_id:
                    issues.append(
                        f"商品 {label} 的 seller 与 sells 里的卖家不一致"
                    )
                buyers = g.get("buyers")
                if isinstance(buyers, list):
                    for buyer_id in buyers:
                        buyer = (
                            merchant_by_id.get(buyer_id)
                            if isinstance(buyer_id, str)
                            else None
                        )
                        if buyer is None:
                            continue
                        buys = buyer.get("buys")
                        if isinstance(buys, list) and name not in buys:
                            issues.append(
                                f"商品 {label} 的买家 {buyer_id} 的 buys 里没有它"
                            )

        return issues

    def summary(self):
        """统计：商品数 / 商人数 / 每条线的商人数 / 每档商品数。"""
        merchants = self.data.get("merchants") or []
        goods = self.data.get("goods") or []

        line_counts = Counter(
            m.get("line")
            for m in merchants
            if isinstance(m, dict)
            and isinstance(m.get("line"), str)
            and m.get("line")
        )
        merchants_by_line = {line: line_counts.get(line, 0) for line in VALID_LINES}
        for line in sorted(set(line_counts) - set(VALID_LINES)):
            merchants_by_line[line] = line_counts[line]

        tier_counts = Counter(
            g.get("tier")
            for g in goods
            if isinstance(g, dict)
            and isinstance(g.get("tier"), str)
            and g.get("tier")
        )
        price_tiers = self.data.get("price_tiers")
        tier_order = (
            list(price_tiers)
            if isinstance(price_tiers, dict)
            else ["tier1", "tier2", "volatile"]
        )
        goods_by_tier = {tier: tier_counts.get(tier, 0) for tier in tier_order}
        for tier in sorted(set(tier_counts) - set(tier_order)):
            goods_by_tier[tier] = tier_counts[tier]

        return {
            "goods": len(goods),
            "merchants": len(merchants),
            "merchants_by_line": merchants_by_line,
            "goods_by_tier": goods_by_tier,
        }

    # ------------------------------------------------------------ 内部工具

    def _as_good(self, value):
        """接受商品 dict 或 key，统一返回知识库里的那个 dict。"""
        if isinstance(value, dict):
            gid = value.get("id")
            if isinstance(gid, str) and gid in self._goods_by_id:
                return self._goods_by_id[gid]
        return self.good(value)

    def _as_merchant(self, value):
        """接受商人 dict 或 key，统一返回知识库里的那个 dict。"""
        if isinstance(value, dict):
            mid = value.get("id")
            if isinstance(mid, str) and mid in self._merchants_by_id:
                return self._merchants_by_id[mid]
        return self.merchant(value)


# ------------------------------------------------------------------ 命令行


def _strip_notes(value):
    """CLI 输出时去掉冗长的 ``note``，其余结构原样保留。"""
    if isinstance(value, dict):
        return {k: _strip_notes(v) for k, v in value.items() if k != "note"}
    if isinstance(value, list):
        return [_strip_notes(v) for v in value]
    return value


def _dump(value):
    text = json.dumps(_strip_notes(value), ensure_ascii=False, indent=2)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - 非 TTY / 老 Python
        pass
    print(text)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m maplebot.trade_graph",
        description="跑商买卖关系图查询",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--good", metavar="KEY", help="查商品：卖家 / 买家 / 档位")
    group.add_argument(
        "--merchant", metavar="KEY", help="查商人：卖什么 / 收什么 / 商机"
    )
    group.add_argument(
        "--from",
        dest="from_merchant",
        metavar="KEY",
        help="查从某商人出发的两跳路线",
    )
    group.add_argument("--validate", action="store_true", help="一致性检查")
    group.add_argument("--stats", action="store_true", help="商品/商人统计")
    args = parser.parse_args(argv)

    try:
        graph = TradeGraph()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"加载知识库失败: {exc}", file=sys.stderr)
        return 2

    try:
        if args.good is not None:
            g = graph.good(args.good)
            payload = {
                "good": g,
                "tier": g.get("tier"),
                "sellers": graph.sellers(g),
                "buyers": graph.buyers(g),
            }
        elif args.merchant is not None:
            m = graph.merchant(args.merchant)
            payload = {
                "merchant": m,
                "sells": graph.sells(m),
                "buys": graph.buys(m),
                "opportunities": graph.opportunities(m),
            }
        elif args.from_merchant is not None:
            m = graph.merchant(args.from_merchant)
            payload = {"from": m, "routes": graph.routes_from(m)}
        elif args.validate:
            issues = graph.validate()
            _dump({"ok": not issues, "issues": issues})
            return 0 if not issues else 1
        else:  # --stats
            _dump(graph.summary())
            return 0
    except KeyError as exc:
        print(f"查询失败: {exc}", file=sys.stderr)
        return 2

    _dump(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
