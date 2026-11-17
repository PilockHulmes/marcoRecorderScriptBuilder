import unittest

from maplebot import goodnames

NAMES = {
    "貴族的布料": "noble_satin",
    "豬肉": "pork",
    "黑水晶碎片": "black_crystal_shard",
}
GOODS = {
    "noble_satin": {"name": "贵族的绸缎", "name_tw": "貴族的布料"},
    "pork": {"name": "猪肉", "name_tw": "豬肉"},
    "soft_silk": {"name": "柔顺的丝绸", "name_tw": "柔軟的綢緞"},
}


class FoldTest(unittest.TestCase):
    def test_simplified_to_traditional(self):
        self.assertEqual(goodnames.fold("贵族的布料"), "貴族的布料")
        self.assertEqual(goodnames.fold("猪肉"), "豬肉")

    def test_unknown_characters_pass_through(self):
        self.assertEqual(goodnames.fold("黑水晶碎片"), "黑水晶碎片")

    def test_empty(self):
        self.assertEqual(goodnames.fold(""), "")
        self.assertEqual(goodnames.fold(None), "")


class ResolveTest(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(goodnames.resolve("貴族的布料", NAMES, GOODS), "noble_satin")

    def test_ocr_returns_a_simplified_lookalike(self):
        self.assertEqual(goodnames.resolve("贵族的布料", NAMES, GOODS), "noble_satin")

    def test_falls_back_to_goods_table(self):
        self.assertEqual(goodnames.resolve("柔顺的丝绸", NAMES, GOODS), "soft_silk")

    def test_fuzzy_match_tolerates_one_wrong_character(self):
        # 五个字里认错一个字（0.8 ≥ 0.7）仍然能对上
        self.assertEqual(goodnames.resolve("黑水晶破片", NAMES, GOODS),
                         "black_crystal_shard")

    def test_unknown_name_returns_empty(self):
        self.assertEqual(goodnames.resolve("完全不存在的東西", NAMES, GOODS), "")
        self.assertEqual(goodnames.resolve("", NAMES, GOODS), "")

    def test_ambiguous_fuzzy_match_is_rejected(self):
        names = {"甲甲": "a", "甲乙": "b"}
        self.assertEqual(goodnames.resolve("甲丙", names, {}), "")


if __name__ == "__main__":
    unittest.main()
