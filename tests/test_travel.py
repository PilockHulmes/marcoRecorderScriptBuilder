"""走图时间估算（maplebot.travel）的单元测试。

所有测试都在临时目录里跑，绝不碰项目自己的 ``data/travel_times.json``。
"""

import json
import statistics
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from maplebot import travel
from maplebot.travel import DEFAULT_SECONDS, TravelTimes


class TravelTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="travel-times-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def make(self, baseline=None, max_samples=50, name="travel_times.json"):
        """构造实例；默认显式传空基准，避免读到仓库里的基准文件。"""
        if baseline is None:
            baseline = {}
        return TravelTimes(
            store_path=self.tmp / name,
            baseline=baseline,
            max_samples=max_samples,
        )


class EstimateTest(TravelTestBase):
    # ---------------------------------------------------------- 空数据
    def test_empty_uses_default(self):
        times = self.make()
        self.assertEqual(
            times.estimate("A", "B"),
            {
                "seconds": DEFAULT_SECONDS,
                "source": "default",
                "n": 0,
                "confidence": "low",
            },
        )
        self.assertEqual(times.walk_seconds("A", "B"), DEFAULT_SECONDS)
        self.assertEqual(times.samples("A", "B"), [])
        self.assertEqual(times.edges(), [])

    def test_default_seconds_constant(self):
        self.assertEqual(DEFAULT_SECONDS, 25.0)

    # ---------------------------------------------------------- 只有基准值
    def test_baseline_only(self):
        times = self.make(baseline={("A", "B"): 42.5})
        self.assertEqual(
            times.estimate("A", "B"),
            {
                "seconds": 42.5,
                "source": "baseline",
                "n": 0,
                "confidence": "low",
            },
        )
        self.assertEqual(times.walk_seconds("A", "B"), 42.5)
        # 反向没有基准值，仍然是 default。
        self.assertEqual(times.estimate("B", "A")["source"], "default")

    # ---------------------------------------------------------- 1~4 条：加权
    def test_few_samples_blend_with_baseline(self):
        baseline_seconds = 100.0
        cases = {
            1: [10.0],
            2: [10.0, 20.0],
            3: [10.0, 20.0, 31.0],
            4: [10.0, 20.0, 31.0, 40.0],
        }
        for count, values in cases.items():
            with self.subTest(n=count):
                times = self.make(baseline={("A", "B"): baseline_seconds})
                for value in values:
                    times.add("A", "B", value)

                personal = statistics.median(values)
                weight = count / 5.0
                expected = personal * weight + baseline_seconds * (1.0 - weight)

                result = times.estimate("A", "B")
                self.assertAlmostEqual(result["seconds"], expected, places=9)
                self.assertEqual(result["source"], "personal_median")
                self.assertEqual(result["n"], count)
                self.assertEqual(result["confidence"], "low")
                # 混合值一定落在个人中位数和基准值之间。
                self.assertGreaterEqual(result["seconds"], min(personal, baseline_seconds))
                self.assertLessEqual(result["seconds"], max(personal, baseline_seconds))

    def test_few_samples_without_baseline_use_personal_median(self):
        times = self.make(baseline={})
        for value in (10.0, 20.0, 30.0):
            times.add("A", "B", value)
        result = times.estimate("A", "B")
        self.assertEqual(result["seconds"], 20.0)
        self.assertEqual(result["source"], "personal_median")
        self.assertEqual(result["n"], 3)
        self.assertEqual(result["confidence"], "low")

    # ---------------------------------------------------------- 5 条：中位数
    def test_five_samples_use_median(self):
        times = self.make(baseline={("A", "B"): 100.0})
        for value in (10.0, 20.0, 30.0, 40.0, 50.0):
            times.add("A", "B", value)
        result = times.estimate("A", "B")
        self.assertEqual(
            result,
            {
                "seconds": 30.0,
                "source": "personal_median",
                "n": 5,
                "confidence": "medium",
            },
        )

    def test_nineteen_samples_still_medium(self):
        times = self.make()
        for value in range(1, 20):
            times.add("A", "B", float(value))
        result = times.estimate("A", "B")
        self.assertEqual(result["source"], "personal_median")
        self.assertEqual(result["confidence"], "medium")
        self.assertEqual(result["seconds"], 10.0)

    # ---------------------------------------------------------- 20+ 条：p90
    def test_twenty_samples_use_p90(self):
        times = self.make(baseline={("A", "B"): 1.0})
        for value in range(1, 21):
            times.add("A", "B", float(value))
        result = times.estimate("A", "B")
        self.assertEqual(result["source"], "personal_p90")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["n"], 20)
        # 中位数 10.5；p90 线性插值 = 18.1；取较大者。
        self.assertAlmostEqual(result["seconds"], 18.1, places=9)
        self.assertGreaterEqual(result["seconds"], statistics.median(range(1, 21)))

    def test_p90_never_below_median(self):
        times = self.make()
        for _ in range(25):
            times.add("A", "B", 30.0)
        result = times.estimate("A", "B")
        self.assertEqual(result["source"], "personal_p90")
        self.assertEqual(result["seconds"], 30.0)

    # ---------------------------------------------------------- 往返
    def test_round_trip_sums_two_directions(self):
        times = self.make(baseline={("A", "B"): 10.0, ("B", "A"): 30.0})
        result = times.round_trip("A", "B")
        self.assertEqual(result["seconds"], 40.0)
        self.assertEqual(result["source"], "baseline")
        self.assertEqual(result["confidence"], "low")
        self.assertEqual(result["n"], 0)
        self.assertEqual(result["forward"]["seconds"], 10.0)
        self.assertEqual(result["backward"]["seconds"], 30.0)

    def test_round_trip_mixes_sources(self):
        times = self.make(baseline={("B", "A"): 100.0})
        for value in (18.0, 20.0, 22.0, 20.0, 20.0):
            times.add("A", "B", value)
        result = times.round_trip("A", "B")
        # 正向 5 条 -> medium；反向只有基准 -> low；往返取更弱的一侧。
        self.assertEqual(result["forward"]["confidence"], "medium")
        self.assertEqual(result["backward"]["confidence"], "low")
        self.assertEqual(result["confidence"], "low")
        self.assertEqual(result["source"], "mixed")
        self.assertAlmostEqual(result["seconds"], 120.0, places=9)
        self.assertEqual(result["n"], 5)

    def test_round_trip_default(self):
        times = self.make()
        result = times.round_trip("A", "B")
        self.assertEqual(result["seconds"], DEFAULT_SECONDS * 2)
        self.assertEqual(result["source"], "default")
        self.assertEqual(result["confidence"], "low")


class SampleTest(TravelTestBase):
    # ---------------------------------------------------------- 异常值
    def test_outliers_are_dropped(self):
        times = self.make()
        bad_values = (
            -1,
            0,
            0.0,
            600.01,
            601,
            float("inf"),
            float("-inf"),
            float("nan"),
            "30",
            None,
            True,
            False,
        )
        for value in bad_values:
            times.add("A", "B", value)
        self.assertEqual(times.samples("A", "B"), [])
        self.assertEqual(times.stats()["edges"], 0)

        # 边界：600 秒本身合法，极小的正数也合法。
        times.add("A", "B", 600)
        times.add("A", "B", 0.001)
        self.assertEqual(times.samples("A", "B"), [600.0, 0.001])

    def test_non_numeric_map_names_are_ignored(self):
        times = self.make()
        times.add(None, "B", 10)
        times.add("A", None, 10)
        times.add("", "B", 10)
        times.add("   ", "B", 10)
        times.add(123, "B", 10)
        self.assertEqual(times.stats()["edges"], 0)

    def test_map_names_are_trimmed(self):
        times = self.make()
        times.add("  A  ", " B ", 10.0)
        self.assertEqual(times.samples("A", "B"), [10.0])
        self.assertEqual(times.samples("  A  ", " B "), [10.0])

    # ---------------------------------------------------------- 上限
    def test_max_samples_keeps_latest(self):
        times = self.make(max_samples=3)
        for value in (1.0, 2.0, 3.0, 4.0, 5.0):
            times.add("A", "B", value)
        self.assertEqual(times.samples("A", "B"), [3.0, 4.0, 5.0])
        self.assertEqual(len(times.samples("A", "B")), 3)

    def test_max_samples_must_be_positive(self):
        with self.assertRaises(ValueError):
            TravelTimes(store_path=self.tmp / "x.json", baseline={}, max_samples=0)
        with self.assertRaises(ValueError):
            TravelTimes(store_path=self.tmp / "x.json", baseline={}, max_samples="oops")

    def test_baseline_type_must_be_mapping(self):
        with self.assertRaises(TypeError):
            TravelTimes(store_path=self.tmp / "x.json", baseline=42)

    def test_samples_returns_copy(self):
        times = self.make()
        times.add("A", "B", 10.0)
        values = times.samples("A", "B")
        values.append(999.0)
        self.assertEqual(times.samples("A", "B"), [10.0])


class PersistenceTest(TravelTestBase):
    # ---------------------------------------------------------- 往返
    def test_save_load_round_trip(self):
        path = self.tmp / "nested" / "travel_times.json"
        times = TravelTimes(store_path=path, baseline={})
        times.add("射手村", "魔法密林", 41.2)
        times.add("射手村", "魔法密林", 39.8)
        times.add("魔法密林", "射手村", 43.0)
        times.save()

        self.assertTrue(path.is_file())
        # 临时文件已被 replace 掉，目录里只剩正式文件。
        self.assertEqual([item.name for item in path.parent.iterdir()], ["travel_times.json"])

        text = path.read_text(encoding="utf-8")
        self.assertIn("射手村", text)  # ensure_ascii=False
        self.assertNotIn("\\u5c04", text)
        raw = json.loads(text)
        self.assertEqual(raw["version"], 1)
        self.assertEqual(len(raw["edges"]), 2)
        self.assertTrue(all("samples" in edge for edge in raw["edges"]))

        # 构造时自动 load。
        loaded = TravelTimes(store_path=path, baseline={})
        self.assertEqual(loaded.samples("射手村", "魔法密林"), [41.2, 39.8])
        self.assertEqual(loaded.samples("魔法密林", "射手村"), [43.0])
        self.assertEqual(loaded.estimate("射手村", "魔法密林"), times.estimate("射手村", "魔法密林"))

        # 显式 load 也应该一致。
        loaded.load()
        self.assertEqual(loaded.samples("射手村", "魔法密林"), [41.2, 39.8])

    def test_load_caps_samples_to_max(self):
        path = self.tmp / "travel_times.json"
        payload = {
            "version": 1,
            "edges": [
                {"from": "A", "to": "B", "samples": [1.0, 2.0, 3.0, 4.0, 5.0]},
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        times = TravelTimes(store_path=path, baseline={}, max_samples=2)
        self.assertEqual(times.samples("A", "B"), [4.0, 5.0])

    def test_load_ignores_bad_entries(self):
        path = self.tmp / "travel_times.json"
        payload = {
            "version": 1,
            "edges": [
                {"from": "A", "to": "B", "samples": [10.0, -1, 0, 601, "20", 12.0]},
                {"from": "A", "to": "C", "samples": "不是列表"},
                {"from": None, "to": "D", "samples": [10.0]},
                "不是对象",
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        times = TravelTimes(store_path=path, baseline={})
        self.assertEqual(times.samples("A", "B"), [10.0, 12.0])
        self.assertEqual(times.stats()["edges"], 1)

    def test_corrupt_store_does_not_wipe_memory(self):
        path = self.tmp / "travel_times.json"
        path.write_text("{ 坏掉的 JSON", encoding="utf-8")
        with self.assertLogs("maplebot.travel", level="WARNING"):
            times = TravelTimes(store_path=path, baseline={})
        self.assertEqual(times.stats()["edges"], 0)

        times.add("A", "B", 10.0)
        with self.assertLogs("maplebot.travel", level="WARNING"):
            times.load()
        self.assertEqual(times.samples("A", "B"), [10.0])

    def test_missing_store_is_empty(self):
        times = self.make(name="does_not_exist.json")
        self.assertEqual(times.stats(), {"edges": 0, "samples": 0, "maps": 0, "with_baseline": 0})

    # ---------------------------------------------------------- 基准文件
    def test_baseline_file_is_loaded(self):
        path = self.tmp / "travel_baseline.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "edges": [
                        {"from": "A", "to": "B", "seconds": 42.5},
                        {"from": "C", "to": "D", "seconds": 77.0},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        with mock.patch.object(travel, "DEFAULT_BASELINE_PATH", path):
            times = TravelTimes(store_path=self.tmp / "travel_times.json")
        self.assertEqual(times.estimate("A", "B")["seconds"], 42.5)
        self.assertEqual(times.estimate("A", "B")["source"], "baseline")
        self.assertEqual(times.estimate("C", "D")["seconds"], 77.0)

    def test_baseline_file_accepts_nested_and_flat_shapes(self):
        path = self.tmp / "travel_baseline.json"
        shapes = (
            {"A": {"B": 12.0}, "C->D": 34.0},
            [{"from": "A", "to": "B", "seconds": 12.0},
             {"from": "C", "to": "D", "seconds": 34.0}],
        )
        for shape in shapes:
            with self.subTest(shape=type(shape).__name__):
                path.write_text(json.dumps(shape, ensure_ascii=False), encoding="utf-8")
                with mock.patch.object(travel, "DEFAULT_BASELINE_PATH", path):
                    times = TravelTimes(store_path=self.tmp / "travel_times.json")
                self.assertEqual(times.estimate("A", "B")["seconds"], 12.0)
                self.assertEqual(times.estimate("C", "D")["seconds"], 34.0)

    def test_invalid_baseline_values_are_ignored(self):
        times = self.make(
            baseline={
                ("A", "B"): -5,
                ("A", "C"): 0,
                ("A", "D"): float("nan"),
                ("A", "E"): "30",
                ("A", "F"): 30.0,
            }
        )
        self.assertNotIn(("A", "B"), times._baseline)
        self.assertNotIn(("A", "D"), times._baseline)
        self.assertEqual(times.estimate("A", "F")["seconds"], 30.0)


class SummaryTest(TravelTestBase):
    def test_stats_counts(self):
        times = self.make(
            baseline={
                ("A", "B"): 50.0,
                ("B", "C"): 60.0,
                ("C", "D"): 70.0,
            }
        )
        times.add("A", "B", 10.0)
        times.add("A", "B", 20.0)
        times.add("A", "B", 30.0)
        times.add("B", "C", 5.0)
        times.add("B", "C", 7.0)
        times.add("D", "E", 9.0)  # 这条边没有基准值

        self.assertEqual(
            times.stats(),
            {
                "edges": 3,
                "samples": 6,
                "maps": 5,
                "with_baseline": 2,
            },
        )

    def test_edges_sorted_with_median(self):
        times = self.make()
        times.add("B", "C", 5.0)
        times.add("B", "C", 7.0)
        times.add("A", "B", 10.0)
        times.add("A", "B", 20.0)
        times.add("A", "B", 30.0)
        times.add("D", "E", 9.0)
        self.assertEqual(
            times.edges(),
            [
                {"from": "A", "to": "B", "n": 3, "median": 20.0},
                {"from": "B", "to": "C", "n": 2, "median": 6.0},
                {"from": "D", "to": "E", "n": 1, "median": 9.0},
            ],
        )

    def test_default_paths_point_at_repo_data(self):
        self.assertEqual(travel.DEFAULT_STORE_PATH, travel.ROOT / "data" / "travel_times.json")
        self.assertEqual(travel.DEFAULT_BASELINE_PATH, travel.ROOT / "data" / "travel_baseline.json")


if __name__ == "__main__":
    unittest.main()
