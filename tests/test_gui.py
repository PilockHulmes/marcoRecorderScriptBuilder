import unittest
from unittest import mock

import numpy as np

from maplebot import advice as advice_module
from maplebot import gui
from maplebot import shop


def make_row(good_id, side, price):
    return shop.Row(good_id, good_id, side, price)


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
        """看板要带 merchant_id / good_id 才能画头像和商品图标。"""
        self.ledger.load.return_value = [{
            "merchant": "石铁", "merchant_id": "dour_4", "map": "A",
            "refresh_in": 120, "t": 1.0,
            "rows": [{"good_id": "pork", "good": "猪肉", "side": "sell", "price": 10}],
        }]
        self.ledger.valid_until = lambda observation: 121.0
        with mock.patch.object(gui.trade, "find_shop_window", return_value=False), \
                mock.patch.object(gui.trade, "find_cargo_window", return_value=False):
            state = self.controller.update(self.frame, now=3.0)
        self.assertEqual(len(state.board), 1)
        entry = state.board[0]
        self.assertEqual(entry["merchant_id"], "dour_4")
        self.assertEqual(entry["until"], 121.0)
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
        self.assertEqual(state.board[0]["merchant_id"], "dour_4")


class BoardFilterTest(unittest.TestCase):
    """看板只保留固定商人，随机商人不能进看板。"""

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
        self.maps = {"A": {"merchant_id": "dour_4"}, "B": {"merchant_id": "kobi_3"}}

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
        self.assertEqual([entry["merchant"] for entry in state.board], ["石铁"])

    def test_all_random_gives_empty_board(self):
        state = self._update([
            {"map": "X", "merchant": "", "merchant_id": "", "t": 1.0, "rows": []},
            {"map": "Y", "merchant": "", "merchant_id": "", "t": 2.0, "rows": []},
        ])
        self.assertEqual(state.board, [])

    def test_old_record_id_falls_back_to_map(self):
        state = self._update([{"merchant": "史莱", "map": "B", "t": 1.0, "rows": []}])
        self.assertEqual(len(state.board), 1)
        self.assertEqual(state.board[0]["merchant_id"], "kobi_3")


def board_entry(merchant, merchant_id, map_name, until, count, start=0):
    rows = [{"good_id": f"g{start + index}", "good": f"商品{start + index}",
             "side": "sell" if index % 2 == 0 else "buy", "price": 10 + index}
            for index in range(count)]
    return {"merchant": merchant, "merchant_id": merchant_id, "map": map_name,
            "until": until, "rows": rows}


class BoardLayoutTest(unittest.TestCase):
    WIDTH = 736
    NOW = 100.0

    def setUp(self):
        self.board = [
            board_entry("石铁", "dour_4", "豐饒的沙漠-1", self.NOW + 200, 3),
            board_entry("藍明", "kobi_3", "豐饒的沙漠-3", self.NOW + 30, 4, start=10),
            board_entry("史莱", "dour_5", "孤獨的沙漠-1", self.NOW - 5, 6, start=20),
            # 随机商人：即使被传进来也必须过滤掉
            board_entry("", "", "某随机地图", self.NOW + 400, 5, start=30),
        ]

    def layout(self, width=None):
        return gui.layout_board(self.board, width or self.WIDTH, now=self.NOW)

    def test_window_size_and_advice_rows(self):
        self.assertEqual((gui.WINDOW_W, gui.WINDOW_H), (760, 930))
        self.assertEqual(gui.ADVICE_ROWS, 8)

    def test_goods_grid(self):
        self.assertEqual(gui._goods_grid(0), (1, 0))
        self.assertEqual(gui._goods_grid(3), (1, 3))
        self.assertEqual(gui._goods_grid(4), (2, 2))
        self.assertEqual(gui._goods_grid(5), (2, 3))
        self.assertEqual(gui._goods_grid(6), (2, 3))

    def test_merchants_use_two_columns(self):
        layout = self.layout()
        self.assertEqual(layout.columns, 2)
        self.assertEqual(layout.column_width, (self.WIDTH - 2 * gui.BOARD_PAD
                                               - gui.COLUMN_GAP) // 2)
        headers = layout.of_kind("merchant")
        self.assertEqual(len(headers), 3)
        left_x = gui.BOARD_PAD
        right_x = gui.BOARD_PAD + layout.column_width + gui.COLUMN_GAP
        self.assertEqual([item.x for item in headers].count(left_x), 2)
        self.assertEqual([item.x for item in headers].count(right_x), 1)
        # 列优先：左列先放前两个商人，第三个换右列
        self.assertEqual([item.owner for item in headers[:2]], ["石铁", "藍明"])
        self.assertEqual(headers[2].owner, "史莱")
        self.assertEqual(layout.split, 2)

    def test_random_merchant_is_not_drawn(self):
        layout = self.layout()
        owners = {item.owner for item in layout.items}
        self.assertNotIn("", owners)
        self.assertEqual([item for item in layout.items if item.kind == "good"
                          and item.text.startswith("商品3")], [])

    def test_every_good_has_a_box_and_none_is_truncated(self):
        layout = self.layout()
        goods = layout.of_kind("good")
        self.assertEqual(len(goods), 3 + 4 + 6)        # 随机商人的 5 件不出现
        for owner, expected in (("石铁", 3), ("藍明", 4), ("史莱", 6)):
            self.assertEqual(len([item for item in goods if item.owner == owner]),
                             expected)

        for item in layout.items:
            self.assertGreaterEqual(item.x, 0)
            self.assertGreaterEqual(item.y, 0)
            self.assertGreater(item.w, 0)
            self.assertGreater(item.h, 0)
            self.assertLessEqual(item.x + item.w, self.WIDTH)
            self.assertLessEqual(item.y + item.h, layout.height)

    def test_goods_wrap_into_columns(self):
        layout = self.layout()
        for owner, columns, rows in (("石铁", 1, 3), ("藍明", 2, 2), ("史莱", 2, 3)):
            goods = [item for item in layout.of_kind("good") if item.owner == owner]
            self.assertEqual(len({item.x for item in goods}), columns, owner)
            self.assertEqual(len({item.y for item in goods}), rows, owner)

    def test_goods_of_six_item_merchant_fit_in_right_column(self):
        layout = self.layout()
        goods = [item for item in layout.of_kind("good") if item.owner == "史莱"]
        self.assertEqual(len(goods), 6)
        goods_width = (layout.column_width - gui.ROW_INDENT) // 2
        self.assertTrue(all(item.w == goods_width for item in goods))
        self.assertLessEqual(max(item.x + item.w for item in goods), self.WIDTH)

    def test_countdown_colors_and_text_are_computed_at_layout_time(self):
        headers = {item.owner: item for item in self.layout().of_kind("merchant")}
        self.assertEqual(headers["石铁"].color, gui.COLOR_GREEN)
        self.assertEqual(headers["石铁"].suffix, "剩 200s")
        self.assertEqual(headers["藍明"].color, gui.COLOR_YELLOW)
        self.assertEqual(headers["藍明"].suffix, "剩 30s")
        self.assertEqual(headers["史莱"].color, gui.COLOR_GRAY)
        self.assertEqual(headers["史莱"].suffix, "已过期")

        # 同一份数据，now 变了倒计时跟着变（没有缓存剩余秒数）
        later = gui.layout_board(self.board, self.WIDTH, now=self.NOW + 250)
        later_headers = {item.owner: item for item in later.of_kind("merchant")}
        self.assertEqual(later_headers["石铁"].suffix, "已过期")
        self.assertEqual(later_headers["石铁"].color, gui.COLOR_GRAY)

    def test_narrow_window_falls_back_to_one_column(self):
        layout = self.layout(width=400)
        self.assertEqual(layout.columns, 1)
        self.assertEqual({item.x for item in layout.of_kind("merchant")},
                         {gui.BOARD_PAD})
        for item in layout.items:
            self.assertLessEqual(item.x + item.w, 400)

    def test_empty_board_placeholder(self):
        for board in ([], [board_entry("", "", "X", self.NOW + 10, 3)]):
            layout = gui.layout_board(board, self.WIDTH, now=self.NOW)
            self.assertEqual(layout.columns, 0)
            self.assertEqual(layout.height, 40)
            self.assertEqual(len(layout.items), 1)
            self.assertEqual(layout.items[0].kind, "placeholder")
            self.assertEqual(layout.items[0].text, "（打开商人界面后显示）")


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
        self.board = [
            board_entry("石铁", "dour_4", "豐饒的沙漠-1", self.NOW + 200, 3),
            board_entry("藍明", "kobi_3", "豐饒的沙漠-3", self.NOW + 30, 4, start=10),
            board_entry("史莱", "dour_5", "孤獨的沙漠-1", self.NOW - 5, 6, start=20),
        ]

    def test_draws_all_text_and_sets_scrollregion(self):
        canvas = FakeCanvas()
        height = gui.draw_board(canvas, self.board, now=self.NOW, icons=None, width=736)
        # 每个商人 2 条文字（标题 + 右对齐倒计时），每件商品 1 条
        self.assertEqual(len(canvas.texts), 3 * 2 + 13)
        self.assertEqual(canvas.images, [])
        self.assertEqual(canvas.scrollregion, (0, 0, 736, height))
        self.assertEqual(gui.layout_board(self.board, 736, now=self.NOW).height, height)
        # 没有商品 -> 空看板占位
        self.assertEqual(gui.draw_board(canvas, [], now=self.NOW, width=736), 40)
        self.assertEqual(len(canvas.texts), 1)

    def test_icons_are_drawn_for_merchants_and_goods(self):
        icons = mock.Mock()
        icons.get.return_value = "photo"
        canvas = FakeCanvas()
        gui.draw_board(canvas, self.board, now=self.NOW, icons=icons, width=736)
        self.assertEqual(len(canvas.images), 3 + 13)
        self.assertEqual(len(canvas.texts), 3 * 2 + 13)


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
