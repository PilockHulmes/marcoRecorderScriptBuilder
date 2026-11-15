"""随机商人的建议：只卖 / 只收两个分支，以及「绝不把他当目的地」。

随机商人 = 没有固定商人的地图上点开交易 UI 遇到的那个 NPC：

- 只有一种类型：要么只卖东西、要么只买东西；
- 玩家一离开地图他就消失，所以不能建议「买了再回来卖给他」；
- ``shop.identify`` 返回 ``("", "", "random")``，记录里的 ``merchant_id`` 为空。
"""

import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from maplebot import advice, ledger, session, shop

#: 合成时间轴一律用墙钟数量级，避免被 Ledger 的 monotonic 防护改写。
BASE = 1_700_000_000.0


GOODS = {
    "cotton": {"name": "棉花", "tier": "tier2", "buyers": ["m_near"]},
    "silk": {"name": "丝绸", "tier": "tier2", "buyers": ["m_mid"]},
    "honey": {"name": "蜂蜜", "tier": "tier2", "buyers": ["m_far"]},
    "pork": {"name": "猪肉", "tier": "tier1", "buyers": ["m_near"]},
}
MAPS = {"m_near": "near_map", "m_mid": "mid_map", "m_far": "far_map"}
NAMES = {"m_near": "近商", "m_mid": "中商", "m_far": "远商"}
# 随机商人所在地图 random_map -> near (1 跳) -> mid (2 跳) -> far (3 跳)
GRAPH = {
    "random_map": ["near_map"],
    "near_map": ["random_map", "mid_map"],
    "mid_map": ["near_map", "far_map"],
    "far_map": ["mid_map"],
}
# 固定商人所在的地图都从 start_map 可达，用来验证随机记录不会被当成目的地
GRAPH_FROM_FIXED = {
    "start_map": ["random_map", "near_map"],
    "random_map": ["start_map"],
    "near_map": ["start_map", "mid_map"],
    "mid_map": ["near_map", "far_map"],
    "far_map": ["mid_map"],
}


@contextlib.contextmanager
def fake_data(goods=None, maps=None, names=None):
    """把知识库固定成上面几个商品/商人/地图，避免依赖真实数据文件。"""
    with mock.patch.object(advice, "_goods", return_value=goods or GOODS), \
            mock.patch.object(advice, "_merchant_maps", return_value=maps or MAPS), \
            mock.patch.object(advice, "_merchant_names", return_value=names or NAMES):
        yield


def make_visit(rows, map_name="random_map", kind="random", coins=50, weight=0,
               capacity=135, refresh=300):
    visit = shop.Visit(map=map_name, merchant="", kind=kind, refresh_in=refresh,
                       coins=coins, weight=weight, capacity=capacity)
    visit.rows = [shop.Row(good_id, GOODS.get(good_id, {}).get("name", good_id),
                           side, price)
                  for good_id, side, price in rows]
    return visit


def observation(map_name, rows, merchant_id="", refresh=600):
    return {"map": map_name, "merchant_id": merchant_id, "merchant": "",
            "merchant_kind": "random" if not merchant_id else "fixed",
            "refresh_in": refresh, "coins": 50, "weight": 0, "capacity": 135,
            "rows": [{"good_id": good_id, "good": GOODS.get(good_id, {}).get("name", good_id),
                      "side": side, "price": price}
                     for good_id, side, price in rows]}


class RandomSellAdviceTest(unittest.TestCase):
    """随机商人只卖货：二类 ≤40、买得起，按到固定买家的距离取最近 1~2 条。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.book = ledger.Ledger(Path(self.tmp.name) / "obs.jsonl")
        self.travel = advice.MapTravel(graph=GRAPH, edge_times=[], per_hop=60)

    def plan(self, rows, now=BASE, coins=50, weight=0):
        visit = make_visit(rows, coins=coins, weight=weight)
        with fake_data():
            return advice.random_sell_plan(visit, self.book, self.travel, now=now)

    def test_sorted_by_distance_and_at_most_two(self):
        items = self.plan([("honey", "sell", 20),     # 3 跳
                           ("silk", "sell", 15),      # 2 跳
                           ("cotton", "sell", 12)])   # 1 跳
        self.assertEqual([item["good"] for item in items], ["棉花", "丝绸"])
        self.assertEqual([item["merchant_id"] for item in items], ["m_near", "m_mid"])
        self.assertEqual([item["seconds"] for item in items], [60.0, 120.0])
        self.assertEqual([item["hops"] for item in items], [1, 2])
        # 目的地必须都是固定商人（merchant_maps.json 里的地图），不是随机图
        self.assertTrue({item["map"] for item in items} <= set(MAPS.values()))
        self.assertNotIn("random_map", {item["map"] for item in items})

    def test_units_are_computed_from_affordability(self):
        items = self.plan([("cotton", "sell", 12)])   # 50 // 12 = 4
        self.assertEqual(items[0]["units"], 4)

    def test_tier1_is_never_recommended(self):
        self.assertEqual(self.plan([("pork", "sell", 10)]), [])

    def test_price_above_tier2_cap_is_never_recommended(self):
        self.assertEqual(self.plan([("cotton", "sell", 41)]), [])

    def test_price_at_tier2_cap_is_kept(self):
        self.assertEqual(len(self.plan([("cotton", "sell", 40)], coins=40)), 1)

    def test_cannot_afford_one_unit(self):
        self.assertEqual(self.plan([("cotton", "sell", 30)], coins=29), [])

    def test_capacity_full(self):
        self.assertEqual(self.plan([("cotton", "sell", 12)], weight=135), [])

    def test_format_shows_known_buyer_price(self):
        self.book.record(observation("near_map", [("cotton", "buy", 22)],
                                     merchant_id="m_near"), now=BASE)
        items = self.plan([("cotton", "sell", 12)])
        with fake_data():
            lines = advice.format_random_sell(items)
        self.assertEqual(
            lines,
            [["在 隨機商人（random_map）",
              "  買 棉花 @12 × 4 個",
              "  → 近商（near_map） 賣 @22",
              "     距离 1 张图"]])

    def test_format_without_buyer_price(self):
        items = self.plan([("silk", "sell", 15)])
        with fake_data():
            lines = advice.format_random_sell(items)
        self.assertEqual(
            lines,
            [["在 隨機商人（random_map）",
              "  買 丝绸 @15 × 3 個",
              "  → 中商（mid_map） 賣",
              "     距离 2 张图"]])

    def test_format_folds_extra_candidates(self):
        items = self.plan([("silk", "sell", 15), ("cotton", "sell", 12)])
        with fake_data():
            lines = advice.format_random_sell(items)
        self.assertEqual(len(lines), 2)          # 两条各占一段，折叠由界面负责

    def test_no_candidate_is_not_a_recommendation(self):
        items = self.plan([("pork", "sell", 10)])
        with fake_data():
            lines = advice.format_random_sell(items)
        self.assertEqual(lines, advice.format_suggestions([]))


class RandomBuyAdviceTest(unittest.TestCase):
    """随机商人只收货：用身上带着的货匹配；没有就明说没有。"""

    def test_held_goods_match_and_count_units(self):
        visit = make_visit([("cotton", "buy", 22)])
        with fake_data():
            items = advice.random_buy_plan(visit, ["cotton", "cotton", "cotton"])
            lines = advice.format_random_buy(items)
        self.assertEqual(items[0]["good"], "棉花")
        self.assertEqual(items[0]["units"], 3)
        self.assertEqual(lines,
                         [["在 隨機商人（random_map）",
                           "  賣 棉花 @22 × 3 個"]])

    def test_no_matching_held_goods(self):
        visit = make_visit([("cotton", "buy", 22)])
        with fake_data():
            lines = advice.format_random_buy(advice.random_buy_plan(visit, ["pork"]))
        self.assertEqual(lines, [["随机商人只收货，你身上没有他要的"]])

    def test_sell_rows_take_priority_over_buy_rows(self):
        """真随机商人只有一种类型；万一读到两种，按卖货型处理，不臆测回头卖。"""
        visit = make_visit([("cotton", "sell", 12), ("silk", "buy", 30)])
        travel = advice.MapTravel(graph=GRAPH, edge_times=[], per_hop=60)
        with tempfile.TemporaryDirectory() as tmp, fake_data():
            book = ledger.Ledger(Path(tmp) / "obs.jsonl")
            blocks = advice.random_advice(visit, book, travel, held=["silk"], now=BASE)
            lines = [line for block in blocks for line in block]
        self.assertTrue(lines[0].startswith("在 隨機商人"))
        self.assertIn("買 ", lines[1])


class RandomNeverDestinationTest(unittest.TestCase):
    """merchant_id 为空的观察只能说明「这里有什么货」，不能当任何目的地。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.book = ledger.Ledger(Path(self.tmp.name) / "obs.jsonl")
        self.book.record(observation("random_map", [("cotton", "sell", 10)]), now=BASE)
        self.travel = advice.MapTravel(graph=GRAPH_FROM_FIXED, edge_times=[],
                                       per_hop=60)

    def test_buy_trip_plan_skips_random_observation(self):
        with fake_data():
            self.assertEqual(
                advice.buy_trip_plan(self.book, self.travel, now=BASE,
                                     current_map="start_map"),
                [])

    def test_sell_plan_skips_random_observation_even_on_same_map(self):
        # 让随机记录的地图恰好等于买家地图：空 merchant_id 仍必须被过滤，
        # 否则随机商人的收购价会变成固定买家的报价/目的地。
        collided = {"m_near": "random_map", "m_mid": "mid_map", "m_far": "far_map"}
        with fake_data(maps=collided):
            plan = advice.sell_plan(["cotton"], self.book, self.travel, now=BASE,
                                    current_map="start_map")
        # 现在"没有已知收购价"也会给方向（谁收是确定的），所以列表不一定为空；
        # 但目的地必须是固定商人，价格不能来自随机商人的记录。
        self.assertTrue(all(item.get("merchant_id") for item in plan))
        self.assertTrue(all(item.get("price") is None for item in plan))

    def test_all_plans_never_point_at_random_map(self):
        with fake_data():
            plans = (
                advice.buy_trip_plan(self.book, self.travel, now=BASE,
                                     current_map="start_map"),
                advice.sell_plan(["cotton"], self.book, self.travel, now=BASE,
                                 current_map="start_map"),
                advice.explore_plan(self.book, self.travel, now=BASE,
                                    current_map="start_map"),
            )
        for plan in plans:
            self.assertNotIn("random_map", {item.get("map") for item in plan})
            self.assertNotIn("随机商人", {item.get("merchant") for item in plan})


class RandomMerchantSessionTest(unittest.TestCase):
    """``TradeSession._read_shop`` 的分支：随机商人不再走三级固定建议。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.book = ledger.Ledger(Path(self.tmp.name) / "obs.jsonl")
        self.watcher = mock.Mock()
        self.watcher.last_map_obs = mock.Mock(map_id="random_map")
        self.travel = advice.MapTravel(graph=GRAPH_FROM_FIXED, edge_times=[],
                                       per_hop=60)
        self.session = session.TradeSession(
            watcher=self.watcher, ledger=self.book, travel=self.travel)
        self.frame = np.zeros((8, 8, 3), np.uint8)

    def _update(self, visit):
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                session.trade, "find_shop_window", return_value=True))
            stack.enter_context(mock.patch.object(
                shop, "read_visit", return_value=visit))
            stack.enter_context(fake_data())
            return self.session.update(self.frame, now=BASE)

    def test_random_sell_branch_is_used(self):
        visit = make_visit([("honey", "sell", 20), ("cotton", "sell", 12)])
        with mock.patch.object(advice, "suggest") as suggest:
            state = self._update(visit)
        suggest.assert_not_called()             # 不再走固定商人的三级建议
        # 两列各一段，每段三行；两列都放得下，所以没有折叠行
        self.assertEqual(len(state.blocks), 2)
        self.assertEqual(state.advice[0], "在 隨機商人（random_map）")
        self.assertIn("買 棉花 @12 × 4 個", state.advice[1])
        self.assertIn("→ 近商（near_map） 賣", state.advice[2])
        self.assertNotIn("到 隨機商人", " ".join(state.advice))   # 随机商人不能是目的地

    def test_random_buy_with_matching_held_goods(self):
        self.session.held = ["cotton", "cotton", "cotton"]
        state = self._update(make_visit([("cotton", "buy", 22)]))
        self.assertEqual(
            state.advice,
            ["在 隨機商人（random_map）",
             "  賣 棉花 @22 × 3 個"])

    def test_random_buy_without_matching_held_goods(self):
        self.session.held = ["pork"]
        state = self._update(make_visit([("cotton", "buy", 22)]))
        self.assertEqual(state.advice, ["随机商人只收货，你身上没有他要的"])

    def test_random_observation_is_recorded_without_merchant_id(self):
        self._update(make_visit([("cotton", "sell", 12)]))
        saved = self.book.load()[-1]
        self.assertEqual(saved["map"], "random_map")
        self.assertEqual(saved["merchant_id"], "")
        self.assertEqual(saved["merchant_kind"], "random")
        self.assertEqual([(row["good_id"], row["side"], row["price"])
                          for row in saved["rows"]],
                         [("cotton", "sell", 12)])

    def test_random_observation_never_becomes_fixed_shop_destination(self):
        # 先留下一条随机商人的记录，随后站在固定商人地图上开店：
        # 建议里不能出现 random_map（不能「买了再回来卖给他」）。
        self.book.record(observation("random_map", [("cotton", "sell", 10)]), now=BASE)
        self.watcher.last_map_obs = mock.Mock(map_id="near_map")
        state = self._update(make_visit([], map_name="near_map", kind="fixed"))
        joined = " ".join(state.advice)
        self.assertNotIn("random_map", joined)
        self.assertNotIn("随机商人", joined)


if __name__ == "__main__":
    unittest.main()
