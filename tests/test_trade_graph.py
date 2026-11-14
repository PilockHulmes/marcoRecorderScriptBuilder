"""跑商买卖关系图的单元测试。

知识库文件缺失时整类 skip（``unittest.SkipTest``），不把环境问题算成失败。
所有测试都只读 ``data/trade/goods.json``，只有 validate 的反例测试会写临时文件。
"""

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from maplebot.trade_graph import TradeGraph, main

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "data" / "trade" / "goods.json"


@unittest.skipUnless(KB.exists(), f"知识库不存在，跳过: {KB}")
class TradeGraphQueryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = TradeGraph(KB)

    # ---------------------------------------------------------- 按名/按 id 查

    def test_good_by_name_and_id(self):
        by_name = self.graph.good("桔梗")
        self.assertEqual(by_name["id"], "balloon_flower")
        self.assertEqual(by_name["tier"], "tier1")
        self.assertIs(self.graph.good("balloon_flower"), by_name)

    def test_good_alias_ginseng(self):
        # 任务里写「人蔘」，知识库实际叫「山参」。
        self.assertEqual(self.graph.good("人蔘")["name"], "山参")
        self.assertEqual(self.graph.good("人参")["name"], "山参")

    def test_merchant_by_name_and_id(self):
        by_id = self.graph.merchant("kobi_1")
        self.assertEqual(by_id["name"], "石铁")
        self.assertEqual(by_id["line"], "kobi")
        self.assertIs(self.graph.merchant("石铁"), by_id)

    def test_unknown_good_raises_key_error(self):
        with self.assertRaises(KeyError):
            self.graph.good("不存在的商品")

    def test_unknown_merchant_raises_key_error(self):
        with self.assertRaises(KeyError):
            self.graph.merchant("不存在的商人")

    # ---------------------------------------------------------- 基础关系

    def test_sellers_of_good(self):
        sellers = self.graph.sellers("桔梗")
        self.assertEqual([m["id"] for m in sellers], ["kobi_1"])

    def test_buyers_of_good(self):
        buyers = self.graph.buyers("桔梗")
        self.assertEqual([m["id"] for m in buyers], ["kobi_5", "ore_5"])
        self.assertEqual([m["line"] for m in buyers], ["kobi", "ore"])

    def test_merchant_sells_and_buys(self):
        m = self.graph.merchant("kobi_1")
        sells = self.graph.sells(m)
        buys = self.graph.buys(m)
        self.assertEqual(len(sells), 2)
        self.assertEqual(len(buys), 4)
        self.assertEqual([g["name"] for g in sells], ["桔梗", "天然蜂蜜"])
        self.assertEqual(
            [g["name"] for g in buys],
            ["银原石", "柔顺的丝绸", "毛毡布料", "白糖"],
        )

    def test_every_good_has_one_seller_and_two_buyers(self):
        for g in self.graph.goods:
            with self.subTest(good=g["id"]):
                self.assertEqual(len(self.graph.sellers(g)), 1)
                self.assertEqual(len(self.graph.buyers(g)), 2)

    def test_every_merchant_sells_two_and_buys_four(self):
        for m in self.graph.merchants:
            with self.subTest(merchant=m["id"]):
                self.assertEqual(len(self.graph.sells(m)), 2)
                self.assertEqual(len(self.graph.buys(m)), 4)

    def test_volatile_good_is_sold_via_goods_seller_only(self):
        # 波动商品不出现在 merchants[].sells 里，但 goods[].seller 仍然唯一。
        g = self.graph.good("wild_ginseng")
        self.assertEqual(g["tier"], "volatile")
        self.assertEqual([m["id"] for m in self.graph.sellers(g)], ["dour_7"])
        self.assertEqual(len(self.graph.buyers(g)), 2)
        self.assertEqual(len(self.graph.sells("dour_7")), 2)

    # ---------------------------------------------------------- 派生查询

    def test_opportunities_structure(self):
        opps = self.graph.opportunities("kobi_1")
        self.assertEqual(len(opps), 2)
        self.assertEqual([o["good"]["name"] for o in opps], ["桔梗", "天然蜂蜜"])
        for item in opps:
            self.assertEqual(
                set(item), {"good", "buyers", "line", "same_line_buyer"}
            )
            self.assertEqual(item["line"], "kobi")
            self.assertIsInstance(item["same_line_buyer"], bool)
            self.assertEqual(len(item["buyers"]), 2)
            self.assertTrue(all(isinstance(b, dict) for b in item["buyers"]))
        self.assertTrue(opps[0]["same_line_buyer"])
        self.assertFalse(opps[1]["same_line_buyer"])

    def test_reverse_opportunities_structure(self):
        items = self.graph.reverse_opportunities("kobi_1")
        self.assertEqual(len(items), 4)
        for item in items:
            self.assertEqual(
                set(item), {"good", "sellers", "line", "same_line_seller"}
            )
            self.assertEqual(item["line"], "kobi")
            self.assertIsInstance(item["same_line_seller"], bool)
            self.assertEqual(len(item["sellers"]), 1)
            self.assertEqual(
                item["sellers"][0]["id"], item["good"]["seller"]
            )

    def test_routes_from_is_exactly_two_hops(self):
        routes = self.graph.routes_from("kobi_1")
        # 2 种在售货 × 每种 2 个买家 = 4 条一跳路线。
        self.assertEqual(len(routes), 4)
        for route in routes:
            self.assertEqual(
                set(route),
                {"from", "good", "buyer", "line", "same_line", "next_goods"},
            )
            self.assertEqual(route["from"]["id"], "kobi_1")
            self.assertIs(self.graph.good(route["good"]), route["good"])
            # 第二跳只列买家在售货，不再递归展开。
            self.assertEqual(
                [g["id"] for g in route["next_goods"]],
                [g["id"] for g in self.graph.sells(route["buyer"])],
            )
            self.assertNotIn("routes", route)

    # ---------------------------------------------------------- validate / summary

    def test_validate_returns_empty_list(self):
        self.assertEqual(self.graph.validate(), [])

    def test_summary(self):
        summary = self.graph.summary()
        self.assertEqual(summary["goods"], 45)
        self.assertEqual(summary["merchants"], 15)
        self.assertEqual(
            summary["merchants_by_line"], {"kobi": 7, "dour": 4, "ore": 4}
        )
        self.assertEqual(
            summary["goods_by_tier"], {"tier1": 15, "tier2": 15, "volatile": 15}
        )

    def test_validate_detects_bad_data(self):
        data = copy.deepcopy(self.graph.data)
        data["merchants"][0]["line"] = "moon"
        data["merchants"][1]["sells"] = data["merchants"][1]["sells"][:1]
        data["goods"][0]["seller"] = "ghost"
        data["goods"][1]["buyers"] = ["nobody", "kobi_5"]
        data["goods"][2]["id"] = data["goods"][3]["id"]

        with tempfile.TemporaryDirectory(prefix="trade-graph-") as tmp:
            path = Path(tmp) / "goods.json"
            path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            issues = TradeGraph(path).validate()

        self.assertTrue(issues)
        text = "\n".join(issues)
        self.assertIn("line 非法", text)
        self.assertIn("sells 应为 2 种", text)
        self.assertIn("seller 不存在", text)
        self.assertIn("buyer 不存在", text)
        self.assertIn("商品 id 重复", text)

    def test_default_path_is_repo_knowledge_base(self):
        self.assertEqual(TradeGraph().path, KB)


@unittest.skipUnless(KB.exists(), f"知识库不存在，跳过: {KB}")
class TradeGraphCliTest(unittest.TestCase):
    """CLI 用进程内调用，不依赖控制台编码；输出仍是 JSON。"""

    def run_main(self, *args):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(list(args))
        return rc, out.getvalue(), err.getvalue()

    def test_good_prints_sellers_buyers_and_tier(self):
        rc, out, _ = self.run_main("--good", "桔梗")
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertEqual(payload["good"]["name"], "桔梗")
        self.assertEqual(payload["tier"], "tier1")
        self.assertEqual([m["id"] for m in payload["sellers"]], ["kobi_1"])
        self.assertEqual(
            [m["id"] for m in payload["buyers"]], ["kobi_5", "ore_5"]
        )

    def test_good_alias_works_from_cli(self):
        rc, out, _ = self.run_main("--good", "人蔘")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["good"]["name"], "山参")

    def test_merchant_prints_sells_buys_and_opportunities(self):
        rc, out, _ = self.run_main("--merchant", "kobi_1")
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertEqual(payload["merchant"]["id"], "kobi_1")
        self.assertEqual(len(payload["sells"]), 2)
        self.assertEqual(len(payload["buys"]), 4)
        self.assertEqual(len(payload["opportunities"]), 2)

    def test_from_prints_two_hop_routes(self):
        rc, out, _ = self.run_main("--from", "kobi_1")
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertEqual(payload["from"]["id"], "kobi_1")
        self.assertEqual(len(payload["routes"]), 4)
        self.assertIn("next_goods", payload["routes"][0])

    def test_validate_prints_ok(self):
        rc, out, _ = self.run_main("--validate")
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["issues"], [])

    def test_stats_prints_summary(self):
        rc, out, _ = self.run_main("--stats")
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertEqual(payload["goods"], 45)
        self.assertEqual(payload["merchants"], 15)

    def test_unknown_key_returns_2(self):
        rc, out, err = self.run_main("--good", "__no_such_good__")
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")
        self.assertIn("未知商品", err)

    def test_no_arguments_is_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                main([])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
