import unittest
from unittest import mock

import numpy as np

from maplebot import advice as advice_module
from maplebot import gui
from maplebot import shop

FIXED_ORDER = [
    "kobi_1", "kobi_2", "kobi_3", "kobi_4", "kobi_5", "kobi_6", "kobi_7",
    "dour_4", "dour_5", "dour_6", "dour_7",
    "ore_4", "ore_5", "ore_6", "ore_7",
]


def make_row(good_id, side, price):
    return shop.Row(good_id, good_id, side, price)


def board_entry(merchant_id, until=None, rows=None, observed=True):
    """布局测试用的观察数据；标题/地图由固定清单补。"""
    return {
        "merchant_id": merchant_id,
        "until": 0.0 if until is None else until,
        "observed": observed,
        "rows": rows or [],
    }


def price_row(good_id, side, price):
    return {"good_id": good_id, "good": good_id, "side": side, "price": price}


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self.ledger = mock.Mock()
        self.ledger.record = lambda visit, now=None: None
        self.ledger.load.return_value = []
        self.ledger.valid_until = lambda observation: 0
        self.watcher = mock.Mock()
        self.watcher.last_map_obs = mock.Mock(map_id="A")
        self.controller = gui.Controller(watcher=self.watcher, ledger=self.ledger,
                                         travel=advice_module.MapTravel(graph={}, edge_times=[]))
        self.frame = np.zeros((8, 8, 3), np.uint8)

    def test_no_windows_no_advice(self):
        with mock.patch.object(gui.trade, "find_shop_window", return_value=False), \
                mock.patch.object(gui.trade, "find_cargo_window", return_value=False):
            state = self.controller.update(self.frame, now=1.0)
        self.assertEqual(state.advice, [])
        self.assertEqual(state.cargo, [])
        self.assertEqual(state.map, "A")

    def test_shop_advice_appears(self):
        visit = shop.Visit(map="A", merchant="石铁", kind="fixed", refresh_in=120,
                           coins=50, weight=0, capacity=135)
        visit.rows = [make_row("g", "sell", 10)]
        with mock.patch.object(gui.trade, "find_shop_window", return_value=True), \
                mock.patch.object(shop, "read_visit", return_value=visit), \
                mock.patch.object(advice_module, "suggest", return_value=[]), \
                mock.patch.object(advice_module, "explore_plan", return_value=[]):
            state = self.controller.update(self.frame, now=1.0)
        self.assertTrue(state.advice)          # 没有生意时至少有一行提示

    def test_shop_throttled(self):
        visit = shop.Visit(map="A", merchant="石铁", kind="fixed", refresh_in=120,
                           coins=50, weight=0, capacity=135)
        visit.rows = [make_row("g", "sell", 10)]
        calls = []
        with mock.patch.object(gui.trade, "find_shop_window", return_value=True), \
                mock.patch.object(shop, "read_visit",
                                  side_effect=lambda f, m: calls.append(1) or visit), \
                mock.patch.object(advice_module, "suggest", return_value=[]), \
                mock.patch.object(advice_module, "explore_plan", return_value=[]):
            self.controller.update(self.frame, now=1.0)     # 打开：立刻读
            self.controller.update(self.frame, now=1.1)     # 节流内：不读
            self.controller.update(self.frame, now=1.5)     # 超过 0.4s：读
        self.assertEqual(len(calls), 2)

    def test_cargo_runs_when_no_shop(self):
        with mock.patch.object(gui.trade, "find_shop_window", return_value=False), \
                mock.patch.object(gui.trade, "find_cargo_window", return_value=True), \
                mock.patch.object(shop, "read_cargo_items", return_value=["g"]), \
                mock.patch.object(advice_module, "sell_plan", return_value=[]):
            state = self.controller.update(self.frame, now=1.0)
        self.assertTrue(state.cargo)

    def test_board_carries_merchant_and_good_ids(self):
        """看板要带 merchant_id / good_id，且没观察的固定商人也保留。"""
        self.ledger.load.return_value = [{
            "merchant": "石铁", "merchant_id": "dour_4", "map": "A",
            "refresh_in": 120, "t": 1.0,
            "rows": [{"good_id": "pork", "good": "猪肉", "side": "sell", "price": 10}],
        }]
        self.ledger.valid_until = lambda observation: 121.0
        with mock.patch.object(gui.trade, "find_shop_window", return_value=False), \
                mock.patch.object(gui.trade, "find_cargo_window", return_value=False):
            state = self.controller.update(self.frame, now=3.0)
        # 固定 15 个商人全部在册，顺序固定
        self.assertEqual([entry["merchant_id"] for entry in state.board], FIXED_ORDER)
        entry = next(item for item in state.board if item["merchant_id"] == "dour_4")
        self.assertEqual(entry["until"], 121.0)
        self.assertTrue(entry["observed"])
        self.assertEqual(entry["rows"][0]["good_id"], "pork")

    def test_board_merchant_id_falls_back_to_map(self):
        """老记录没有 merchant_id 时按地图反查。"""
        self.ledger.load.return_value = [{
            "merchant": "史莱", "map": "A", "refresh_in": 60, "t": 1.0, "rows": [],
        }]
        self.ledger.valid_until = lambda observation: 61.0
        with mock.patch.object(gui.trade, "find_shop_window", return_value=False), \
                mock.patch.object(gui.trade, "find_cargo_window", return_value=False), \
                mock.patch.object(gui.shop, "load_merchant_maps",
                                  return_value={"A": {"merchant_id": "dour_4"}}):
            state = self.controller.update(self.frame, now=3.0)
        self.assertEqual(len(state.board), 1)
        self.assertEqual(state.board[0]["merchant_id"], "dour_4")
        self.assertTrue(state.board[0]["observed"])


class BoardFilterTest(unittest.TestCase):
    """看板固定显示 merchant_maps.json 里的商人，随机商人不进看板。"""

    def setUp(self):
        self.ledger = mock.Mock()
        self.ledger.load.return_value = []
        self.ledger.valid_until = lambda observation: observation.get("until", 0)
        self.watcher = mock.Mock()
        self.watcher.last_map_obs = mock.Mock(map_id="A")
        self.controller = gui.Controller(
            watcher=self.watcher, ledger=self.ledger,
            travel=advice_module.MapTravel(graph={}, edge_times=[]))
        self.frame = np.zeros((8, 8, 3), np.uint8)
        self.maps = {
            "A": {"merchant_id": "dour_4", "merchant": "史莱", "game_name": "史來"},
            "B": {"merchant_id": "kobi_3", "merchant": "兰明", "game_name": "藍明"},
        }

    def _update(self, observations):
        self.ledger.load.return_value = observations
        with mock.patch.object(gui.trade, "find_shop_window", return_value=False), \
                mock.patch.object(gui.trade, "find_cargo_window", return_value=False), \
                mock.patch.object(gui.shop, "load_merchant_maps", return_value=self.maps):
            return self.controller.update(self.frame, now=3.0)

    @staticmethod
    def fixed(merchant, merchant_id, map_name, t=1.0, rows=None):
        return {"merchant": merchant, "merchant_id": merchant_id,
                "map": map_name, "t": t, "rows": rows or []}

    def test_drops_random_and_unknown_merchants(self):
        state = self._update([
            self.fixed("石铁", "dour_4", "A"),
            # 随机商人：两个字段都空
            {"map": "X", "merchant": "", "merchant_id": "", "t": 2.0, "rows": []},
            # 有名字但没有 merchant_id，地图也查不到
            {"map": "Y", "merchant": "神秘商人", "merchant_id": "", "t": 3.0, "rows": []},
            # merchant_id 不在 merchant_maps.json 里
            self.fixed("无名", "ghost_1", "Z", t=4.0),
        ])
        self.assertEqual([entry["merchant_id"] for entry in state.board],
                         ["kobi_3", "dour_4"])
        by_id = {entry["merchant_id"]: entry for entry in state.board}
        self.assertTrue(by_id["dour_4"]["observed"])
        self.assertFalse(by_id["kobi_3"]["observed"])
        self.assertNotIn("ghost_1", by_id)

    def test_all_random_still_renders_fixed_merchants(self):
        state = self._update([
            {"map": "X", "merchant": "", "merchant_id": "", "t": 1.0, "rows": []},
            {"map": "Y", "merchant": "", "merchant_id": "", "t": 2.0, "rows": []},
        ])
        # 没有观察记录也固定返回两个商人（位置不能少）
        self.assertEqual([entry["merchant_id"] for entry in state.board],
                         ["kobi_3", "dour_4"])
        self.assertTrue(all(not entry["observed"] for entry in state.board))

    def test_old_record_id_falls_back_to_map(self):
        state = self._update([{"merchant": "史莱", "map": "B", "t": 1.0, "rows": []}])
        self.assertEqual(len(state.board), 2)
        entry = next(item for item in state.board if item["merchant_id"] == "kobi_3")
        self.assertTrue(entry["observed"])


class BoardLayoutTest(unittest.TestCase):
    WIDTH = 736
    NOW = 100.0

    def setUp(self):
        self.maps = {
            "M1": {"merchant_id": "kobi_1", "merchant": "石铁", "game_name": "石鉄"},
            "M2": {"merchant_id": "dour_4", "merchant": "史莱", "game_name": "史來"},
            "M3": {"merchant_id": "ore_7", "merchant": "哲里", "game_name": "哲利"},
        }

    def layout(self, board=None, width=None, now=None, goods=None, maps=None):
        with mock.patch.object(gui.shop, "load_merchant_maps",
                               return_value=maps if maps is not None else self.maps):
            if goods is not None:
                with mock.patch.object(gui.shop, "load_goods", return_value=goods):
                    return gui.layout_board(board or [], width or self.WIDTH,
                                            now=self.NOW if now is None else now)
            return gui.layout_board(board or [], width or self.WIDTH,
                                    now=self.NOW if now is None else now)

    def test_window_size_and_advice_rows(self):
        self.assertEqual((gui.WINDOW_W, gui.WINDOW_H), (760, 930))
        self.assertEqual(gui.ADVICE_ROWS, 8)

    def test_fixed_order_is_line_then_number(self):
        layout = self.layout()
        self.assertEqual([item.icon_key for item in layout.of_kind("merchant")],
                         ["kobi_1", "dour_4", "ore_7"])
        self.assertEqual(layout.split, 2)          # 3 个 -> 左 2 右 1

    def test_all_fixed_merchants_render_without_any_data(self):
        layout = self.layout()
        headers = layout.of_kind("merchant")
        goods = layout.of_kind("good")
        self.assertEqual(len(headers), 3)
        self.assertEqual(len(goods), 3 * gui.GOODS_SLOTS)
        for header in headers:
            self.assertEqual(header.suffix, gui.UNSEEN_TEXT)
            self.assertEqual(header.suffix_color, gui.COLOR_UNSEEN)
            self.assertEqual(header.color, gui.COLOR_ROW)   # 标题正常显示
        self.assertTrue(all(item.price_text == gui.PRICE_EMPTY for item in goods))
        self.assertTrue(all(item.text == gui.PRICE_EMPTY
                            for item in goods if not item.good_id))

    def test_every_merchant_has_fixed_two_by_four_slots(self):
        layout = self.layout()
        for owner in ("石鉄", "史來", "哲利"):
            goods = [item for item in layout.of_kind("good") if item.owner == owner]
            self.assertEqual(len(goods), gui.GOODS_SLOTS)
            self.assertEqual({item.slot for item in goods}, set(range(gui.GOODS_SLOTS)))
            self.assertEqual(len({item.x for item in goods}), 2)
            self.assertEqual(len({item.y for item in goods}), 4)
            self.assertEqual(len({item.w for item in goods}), 1)

    def test_goods_slots_are_sells_then_buys_in_file_order(self):
        goods = {
            "s1": {"id": "s1", "name": "卖一", "seller": "kobi_1", "buyers": []},
            "s2": {"id": "s2", "name": "卖二", "seller": "kobi_1", "buyers": []},
            "s3": {"id": "s3", "name": "波动", "tier": "volatile",
                   "seller": "kobi_1", "buyers": []},
            "b1": {"id": "b1", "name": "收一", "buyers": ["kobi_1"]},
            "b2": {"id": "b2", "name": "收二", "buyers": ["kobi_1"]},
            "b3": {"id": "b3", "name": "收三", "buyers": ["kobi_1"]},
            "b4": {"id": "b4", "name": "收四", "buyers": ["kobi_1"]},
            "b5": {"id": "b5", "name": "收五", "buyers": ["kobi_1"]},
        }
        layout = self.layout(goods=goods)
        slots = sorted((item for item in layout.of_kind("good")
                        if item.owner == "石鉄"), key=lambda item: item.slot)
        self.assertEqual([item.good_id for item in slots],
                         ["s1", "s2", "s3", "b1", "b2", "b3", "b4", ""])
        self.assertEqual([item.side for item in slots],
                         ["sell", "sell", "sell", "buy", "buy", "buy", "buy", ""])

    def test_empty_slots_are_padded_to_eight(self):
        maps = dict(self.maps)
        maps["M9"] = {"merchant_id": "kobi_99", "merchant": "空商人",
                      "game_name": "空商人"}
        layout = self.layout(maps=maps)
        empty = [item for item in layout.of_kind("good") if item.owner == "空商人"]
        self.assertEqual(len(empty), gui.GOODS_SLOTS)
        self.assertTrue(all(item.good_id == "" for item in empty))
        self.assertTrue(all(item.text == gui.PRICE_EMPTY for item in empty))

    def test_prices_fill_fixed_slots(self):
        board = [board_entry("kobi_1", until=self.NOW + 100, rows=[
            price_row("natural_honey", "sell", 12),
            price_row("silver_ore", "buy", 30),
        ])]
        layout = self.layout(board)
        by_good = {item.good_id: item for item in layout.of_kind("good")
                   if item.owner == "石鉄"}
        self.assertEqual(by_good["natural_honey"].price_text, "12")
        self.assertEqual(by_good["silver_ore"].price_text, "30")
        self.assertEqual(by_good["natural_honey"].label_color, gui.COLOR_SELL)
        self.assertEqual(by_good["silver_ore"].label_color, gui.COLOR_BUY)
        # 这次没上架/没记录的商品：价格「—」且标签用浅灰
        self.assertEqual(by_good["balloon_flower"].price_text, gui.PRICE_EMPTY)
        self.assertEqual(by_good["balloon_flower"].label_color, gui.COLOR_GRAY)

    def test_expired_observation_hides_old_prices(self):
        board = [board_entry("kobi_1", until=self.NOW - 5, rows=[
            price_row("natural_honey", "sell", 999),
            price_row("silver_ore", "buy", 888),
        ])]
        layout = self.layout(board)
        header = next(item for item in layout.of_kind("merchant")
                      if item.icon_key == "kobi_1")
        self.assertEqual(header.suffix, gui.EXPIRED_TEXT)
        self.assertEqual(header.color, gui.COLOR_GRAY)
        goods = [item for item in layout.of_kind("good") if item.owner == "石鉄"]
        self.assertTrue(all(item.price_text == gui.PRICE_EMPTY for item in goods))
        self.assertTrue(all(item.label_color == gui.COLOR_GRAY for item in goods))
        self.assertNotIn("999", [item.price_text for item in goods])
        self.assertNotIn("888", [item.price_text for item in goods])

    def test_sell_and_buy_use_different_colors(self):
        board = [board_entry("kobi_1", until=self.NOW + 100, rows=[
            price_row("natural_honey", "sell", 12),
            price_row("silver_ore", "buy", 30),
        ])]
        layout = self.layout(board)
        by_good = {item.good_id: item for item in layout.of_kind("good")
                   if item.owner == "石鉄"}
        sell, buy = by_good["natural_honey"], by_good["silver_ore"]
        self.assertEqual(sell.label, "卖")
        self.assertEqual(buy.label, "收")
        self.assertEqual(sell.label_color, gui.COLOR_SELL)
        self.assertEqual(buy.label_color, gui.COLOR_BUY)
        self.assertNotEqual(sell.label_color, buy.label_color)
        # 商品名保持深灰
        self.assertEqual(sell.color, gui.COLOR_ROW)
        self.assertEqual(buy.color, gui.COLOR_ROW)

    def test_name_label_and_price_have_three_fixed_x_positions(self):
        board = [board_entry("kobi_1", until=self.NOW + 100, rows=[
            price_row("natural_honey", "sell", 12),
        ])]
        layout = self.layout(board)
        item = next(good for good in layout.of_kind("good")
                    if good.good_id == "natural_honey")
        self.assertLess(item.name_x, item.label_x)
        self.assertLess(item.label_x, item.price_x)
        self.assertEqual(item.name_x, item.x + gui.ICON_SIZE + gui.ICON_GAP)
        self.assertEqual(item.price_x, item.x + item.w - gui.PRICE_RIGHT_OFFSET)
        self.assertEqual(item.label_x, item.x + item.w - gui.LABEL_RIGHT_OFFSET)

    def test_positions_do_not_change_when_prices_arrive(self):
        empty = self.layout()
        priced = self.layout([
            board_entry("kobi_1", until=self.NOW + 100, rows=[
                price_row("natural_honey", "sell", 12),
                price_row("silver_ore", "buy", 30),
            ]),
            board_entry("dour_4", until=self.NOW + 30, rows=[]),
            board_entry("ore_7", until=self.NOW - 5, rows=[]),
        ])
        headers = lambda layout: [(item.icon_key, item.x, item.y, item.w, item.h)
                                  for item in layout.of_kind("merchant")]
        goods = lambda layout: [(item.owner, item.slot, item.good_id,
                                 item.x, item.y, item.w, item.h)
                                for item in layout.of_kind("good")]
        self.assertEqual(headers(empty), headers(priced))
        self.assertEqual(goods(empty), goods(priced))
        self.assertEqual(len(goods(priced)), 3 * gui.GOODS_SLOTS)

    def test_countdown_colors_and_text_are_computed_at_layout_time(self):
        board = [
            board_entry("kobi_1", until=self.NOW + 200),
            board_entry("dour_4", until=self.NOW + 30),
            board_entry("ore_7", until=self.NOW - 5),
        ]
        headers = {item.icon_key: item for item in self.layout(board).of_kind("merchant")}
        self.assertEqual(headers["kobi_1"].color, gui.COLOR_GREEN)
        self.assertEqual(headers["kobi_1"].suffix, "剩 200s")
        self.assertEqual(headers["dour_4"].color, gui.COLOR_YELLOW)
        self.assertEqual(headers["dour_4"].suffix, "剩 30s")
        self.assertEqual(headers["ore_7"].color, gui.COLOR_GRAY)
        self.assertEqual(headers["ore_7"].suffix, gui.EXPIRED_TEXT)

        later = self.layout(board, now=self.NOW + 250)
        later_headers = {item.icon_key: item for item in later.of_kind("merchant")}
        self.assertEqual(later_headers["kobi_1"].suffix, gui.EXPIRED_TEXT)
        self.assertEqual(later_headers["kobi_1"].color, gui.COLOR_GRAY)

    def test_random_merchant_is_not_drawn(self):
        layout = self.layout([board_entry("ghost_1", until=self.NOW + 400),
                              board_entry("", observed=False)])
        self.assertEqual([item.icon_key for item in layout.of_kind("merchant")],
                         ["kobi_1", "dour_4", "ore_7"])
        self.assertNotIn("", {item.owner for item in layout.items})

    def test_narrow_window_falls_back_to_one_column(self):
        layout = self.layout(width=400)
        self.assertEqual(layout.columns, 1)
        self.assertEqual({item.x for item in layout.of_kind("merchant")},
                         {gui.BOARD_PAD})
        for item in layout.items:
            self.assertLessEqual(item.x + item.w, 400)

    def test_nothing_overflows_right_or_bottom(self):
        for width in (self.WIDTH, 400):
            layout = self.layout(width=width)
            for item in layout.items:
                self.assertGreaterEqual(item.x, 0)
                self.assertGreaterEqual(item.y, 0)
                self.assertGreater(item.w, 0)
                self.assertGreater(item.h, 0)
                self.assertLessEqual(item.x + item.w, width)
                self.assertLessEqual(item.y + item.h, layout.height)

    def test_empty_board_placeholder_when_merchant_maps_missing(self):
        layout = self.layout(maps={})
        self.assertEqual(layout.columns, 0)
        self.assertEqual(len(layout.items), 1)
        self.assertEqual(layout.items[0].kind, "placeholder")


class RealFixedMerchantDataTest(unittest.TestCase):
    """用仓库里的真实 merchant_maps.json / goods.json 验证固定 15 个。"""

    def test_fifteen_merchants_in_fixed_order_with_eight_slots_each(self):
        layout = gui.layout_board([], 736, now=100.0)
        headers = layout.of_kind("merchant")
        self.assertEqual([item.icon_key for item in headers], FIXED_ORDER)
        self.assertEqual(layout.split, 8)          # 左 8 右 7
        goods = layout.of_kind("good")
        self.assertEqual(len(goods), 15 * gui.GOODS_SLOTS)
        for header in headers:
            slots = [item for item in goods if item.owner == header.owner]
            self.assertEqual(len(slots), gui.GOODS_SLOTS, header.icon_key)

    def test_empty_data_all_prices_dash_and_all_unseen(self):
        layout = gui.layout_board([], 736, now=100.0)
        self.assertTrue(all(item.suffix == gui.UNSEEN_TEXT
                            for item in layout.of_kind("merchant")))
        self.assertTrue(all(item.price_text == gui.PRICE_EMPTY
                            for item in layout.of_kind("good")))


class FakeCanvas:
    def __init__(self, width=736):
        self._width = width
        self.texts = []
        self.images = []
        self.scrollregion = None

    def winfo_width(self):
        return self._width

    def delete(self, *args):
        self.texts.clear()
        self.images.clear()

    def configure(self, **kwargs):
        self.scrollregion = kwargs.get("scrollregion")

    def create_text(self, x, y, **kwargs):
        self.texts.append((x, y, kwargs))
        return len(self.texts)

    def create_image(self, x, y, **kwargs):
        self.images.append((x, y, kwargs))
        return len(self.images)


class DrawBoardTest(unittest.TestCase):
    NOW = 100.0

    def setUp(self):
        self.maps = {
            "M1": {"merchant_id": "kobi_1", "merchant": "石铁", "game_name": "石鉄"},
            "M2": {"merchant_id": "dour_4", "merchant": "史莱", "game_name": "史來"},
            "M3": {"merchant_id": "ore_7", "merchant": "哲里", "game_name": "哲利"},
        }
        self.board = [
            board_entry("kobi_1", until=self.NOW + 200, rows=[
                price_row("natural_honey", "sell", 12),
                price_row("silver_ore", "buy", 30),
            ]),
            board_entry("dour_4", until=self.NOW + 30),
            board_entry("ore_7", until=self.NOW - 5),
        ]

    def draw(self, board=None, icons=None, width=736):
        canvas = FakeCanvas(width)
        with mock.patch.object(gui.shop, "load_merchant_maps", return_value=self.maps):
            height = gui.draw_board(canvas, self.board if board is None else board,
                                    now=self.NOW, icons=icons, width=width)
        return canvas, height

    @staticmethod
    def expected_text_count():
        # 每个商人：标题 + 倒计时 + 7 个有货槽位×3 段文字 + 1 个空槽位
        return 3 * (2 + 7 * 3 + 1)

    def test_draws_all_text_and_sets_scrollregion(self):
        canvas, height = self.draw()
        self.assertEqual(len(canvas.texts), self.expected_text_count())
        self.assertEqual(canvas.images, [])
        with mock.patch.object(gui.shop, "load_merchant_maps", return_value=self.maps):
            layout = gui.layout_board(self.board, 736, now=self.NOW)
        self.assertEqual(canvas.scrollregion, (0, 0, 736, height))
        self.assertEqual(layout.height, height)
        self.assertIn("—", [kwargs.get("text") for _, _, kwargs in canvas.texts])

    def test_icons_are_drawn_for_merchants_and_goods(self):
        icons = mock.Mock()
        icons.get.return_value = "photo"
        canvas, _ = self.draw(icons=icons)
        self.assertEqual(len(canvas.images), 3 + 3 * 7)
        self.assertEqual(len(canvas.texts), self.expected_text_count())

    def test_price_text_is_right_aligned(self):
        canvas, _ = self.draw()
        with mock.patch.object(gui.shop, "load_merchant_maps", return_value=self.maps):
            layout = gui.layout_board(self.board, 736, now=self.NOW)
        item = next(good for good in layout.of_kind("good")
                    if good.good_id == "natural_honey")
        prices = [(x, y, kwargs) for x, y, kwargs in canvas.texts
                  if kwargs.get("text") == "12"]
        self.assertEqual(len(prices), 1)
        x, _, kwargs = prices[0]
        self.assertEqual(kwargs["anchor"], "e")
        self.assertEqual(x, item.price_x)
        self.assertGreater(x, item.label_x)

    def test_sell_and_buy_labels_are_colored_differently(self):
        canvas, _ = self.draw()
        fills = {}
        for _, _, kwargs in canvas.texts:
            if kwargs.get("text") in ("卖", "收"):
                fills.setdefault(kwargs["text"], set()).add(kwargs["fill"])
        self.assertIn(gui.COLOR_SELL, fills["卖"])
        self.assertIn(gui.COLOR_BUY, fills["收"])
        self.assertNotEqual(gui.COLOR_SELL, gui.COLOR_BUY)
        # 这次没有有效价格的槽位用浅灰
        self.assertIn(gui.COLOR_GRAY, fills["卖"])
        self.assertIn(gui.COLOR_GRAY, fills["收"])

    def test_expired_prices_are_drawn_as_dash_not_old_numbers(self):
        board = [board_entry("kobi_1", until=self.NOW - 5, rows=[
            price_row("natural_honey", "sell", 999),
            price_row("silver_ore", "buy", 888),
        ])]
        canvas, _ = self.draw(board=board)
        texts = [kwargs.get("text") for _, _, kwargs in canvas.texts]
        self.assertNotIn("999", texts)
        self.assertNotIn("888", texts)
        self.assertIn(gui.EXPIRED_TEXT, texts)

    def test_empty_board_draws_every_fixed_merchant(self):
        canvas, height = self.draw(board=[])
        self.assertEqual(len(canvas.texts), self.expected_text_count())
        labels = [kwargs.get("text") for _, _, kwargs in canvas.texts]
        self.assertEqual(labels.count(gui.UNSEEN_TEXT), 3)
        self.assertEqual(labels.count(gui.PRICE_EMPTY), 3 * gui.GOODS_SLOTS)


class StatusColorTest(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(gui.status_color(61), gui.COLOR_GREEN)
        self.assertEqual(gui.status_color(60), gui.COLOR_YELLOW)
        self.assertEqual(gui.status_color(0), gui.COLOR_GRAY)
        self.assertEqual(gui.status_color(-5), gui.COLOR_GRAY)


class IconKeyTest(unittest.TestCase):
    def test_rejects_path_traversal(self):
        self.assertTrue(gui._valid_key("pork"))
        self.assertFalse(gui._valid_key(""))
        self.assertFalse(gui._valid_key("../pork"))
        self.assertFalse(gui._valid_key("icons/pork"))
        self.assertFalse(gui._valid_key(None))


if __name__ == "__main__":
    unittest.main()
