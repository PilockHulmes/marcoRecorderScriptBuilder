"""``maplebot.mapwatch`` 的合成帧单元测试（不碰真实游戏窗口 / PaddleOCR）。

覆盖这次修掉的一组 bug：

1. 地图名统一由 ``step()`` 解析（模板 -> OCR + 纠错），指纹只能留在
   ``Observation.raw``，绝不会变成 ``map_id``；
2. 名字解析失败就是空串，不写事件、不进报告（也不再有"未知地图"）；
3. 玩家位置未知时 ``player is None``，不聚类、不写盘，更不会写 (0, 0)；
4. ``explored`` / ``unexplored`` 用同一个 ``pos_key``；
5. 坐标统一用 (dx/width, dy/height)，传送门按 5px 像素半径聚类，key 稳定；
6. 坏 jsonl 行、损坏的 seen_portals.json、``_Tee`` 的文件接口都有容错。

所有落盘路径都来自 ``tempfile.mkdtemp()``，不会写进项目 ``data/``。
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from maplebot import mapwatch, minimap


def make_obs(raw="", player=(0.5, 0.5), size=(165, 48), dark=False, portals=()):
    """造一帧 Observation（map_id 故意留空，交给 step 解析）。"""
    return mapwatch.Observation(raw=raw, player=player, size=size, dark=dark,
                                portals=list(portals))


class MapWatchTestBase(unittest.TestCase):
    """公共夹具：tmp 路径 + monkeypatch 掉观察/命名/OCR 依赖。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mapwatch-test-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.visits = self.tmp / "data" / "map_visits.jsonl"
        self.portals = self.tmp / "data" / "seen_portals.json"
        self.names = self.tmp / "data" / "map_names.json"
        self._names = []
        self._script = []

        def fake_match(crop, threshold=mapwatch.NAME_THRESHOLD):
            # 只按脚本发名字；脚本用尽就当作"模板没命中"
            if self._names:
                return self._names.pop(0), 0.99
            return "", 0.0

        patches = [
            # 名字截图区域：给一块合成图，避免依赖真实小地图
            mock.patch.object(mapwatch, "name_crop",
                              return_value=np.zeros((40, 160, 3), np.uint8)),
            mock.patch.object(mapwatch, "match_name", side_effect=fake_match),
            # 绝不启用 PaddleOCR（连实例都不造）
            mock.patch.object(mapwatch, "read_map_name", return_value=("", "")),
            mock.patch.object(mapwatch.MapWatcher, "_ocr_instance", return_value=object()),
            # 模板落盘会写项目 data/，测试里直接吞掉
            mock.patch.object(mapwatch, "save_name_template"),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_watcher(self):
        return mapwatch.MapWatcher(
            visits_path=str(self.visits),
            portals_path=str(self.portals),
            names_path=str(self.names),
        )

    def feed(self, frames, names=()):
        """让 observe 按顺序返回 frames；match_name 按顺序返回 names。"""
        self._script = list(frames)
        self._names = list(names)

        def fake_observe(frame):
            return self._script.pop(0) if self._script else None

        patcher = mock.patch.object(mapwatch, "observe", side_effect=fake_observe)
        patcher.start()
        self.addCleanup(patcher.stop)

    def read_events(self):
        if not self.visits.exists():
            return []
        return [json.loads(line) for line in
                self.visits.read_text(encoding="utf-8").splitlines() if line.strip()]


class NameAndEdgeTest(MapWatchTestBase):
    def test_a_dark_transition_uses_names_not_fingerprint(self):
        """A → 黑屏 → B：只产生 1 条事件，id 是名字不是指纹。"""
        raw_a = "a" * 1024      # 模拟旧版本 1024 字符指纹
        raw_b = "b" * 1024
        frames = [
            make_obs(raw=raw_a, player=(0.2, 0.3)),
            make_obs(raw="", player=None, dark=True),
            make_obs(raw=raw_b, player=(0.8, 0.7)),
        ]
        self.feed(frames, names=["A", "B"])
        watcher = self.make_watcher()

        self.assertIsNone(watcher.step(object(), now=1.0))   # 进场 A
        self.assertIsNone(watcher.step(object(), now=1.5))   # 黑屏
        event = watcher.step(object(), now=2.0)              # 到 B
        self.assertIsNotNone(event)
        self.assertEqual(event["from_map"], "A")
        self.assertEqual(event["to_map"], "B")
        self.assertEqual(event["from_pos"], [0.2, 0.3])
        self.assertEqual(event["to_pos"], [0.8, 0.7])

        events = self.read_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["from_map"], "A")
        self.assertEqual(events[0]["to_map"], "B")
        for key in ("from_map", "to_map"):
            self.assertLessEqual(len(events[0][key]), mapwatch.MAX_ID_LEN)
            self.assertNotEqual(events[0][key], raw_a)
            self.assertNotEqual(events[0][key], raw_b)
        for value in events[0].values():
            self.assertNotEqual(value, raw_a)
            self.assertNotEqual(value, raw_b)

        # 指纹只留在 raw，step 解析后的 map_id 是名字
        self.assertEqual(frames[0].raw, raw_a)
        self.assertEqual(frames[0].map_id, "A")
        self.assertEqual(frames[2].map_id, "B")

        report = watcher.report()
        self.assertEqual({item["id"] for item in report["maps"]}, {"A", "B"})
        self.assertEqual(len(report["edges"]), 1)

    def test_b_round_trip_no_dark_edges_and_unexplored(self):
        """A → B → A → B（不黑屏）：maps=2、两条有向边、未跑不再增长。"""
        frames = [
            make_obs(player=(0.1, 0.2)),
            make_obs(player=(0.6, 0.7)),
            make_obs(player=(0.1, 0.2)),
            make_obs(player=(0.6, 0.7)),
        ]
        self.feed(frames, names=["A", "B", "A", "B"])
        watcher = self.make_watcher()

        self.assertIsNone(watcher.step(object()))            # 进场 A
        first = watcher.step(object())
        self.assertEqual((first["from_map"], first["to_map"]), ("A", "B"))
        self.assertEqual(len(watcher.report()["unexplored"]), 1)   # B 的落点还没跑过

        second = watcher.step(object())                      # 一次往返
        self.assertEqual((second["from_map"], second["to_map"]), ("B", "A"))
        after_round_trip = len(watcher.report()["unexplored"])
        self.assertEqual(after_round_trip, 0)

        third = watcher.step(object())                       # 再走一次
        self.assertEqual((third["from_map"], third["to_map"]), ("A", "B"))
        self.assertEqual(len(watcher.report()["unexplored"]), after_round_trip)

        report = watcher.report()
        self.assertEqual(len(report["maps"]), 2)
        self.assertEqual(len(report["edges"]), 2)
        edges = {(item["from"], item["to"]): item["count"] for item in report["edges"]}
        self.assertEqual(edges, {("A", "B"): 2, ("B", "A"): 1})

    def test_c_name_failure_records_nothing(self):
        """名字解析失败：不产生事件，报告里也没有空 id / 旧占位符 / 指纹。"""
        watcher = self.make_watcher()          # 先建，避免预置脏数据被 _replay 吃掉
        self.visits.parent.mkdir(parents=True, exist_ok=True)
        legacy = [
            {"from_map": "A", "from_pos": [0.1, 0.1],
             "to_map": "", "to_pos": [0.2, 0.2]},
            {"from_map": "A", "from_pos": [0.1, 0.1],
             "to_map": mapwatch.LEGACY_UNKNOWN, "to_pos": [0.2, 0.2]},
            {"from_map": "c" * 1024, "from_pos": [0.1, 0.1],
             "to_map": "B", "to_pos": [0.2, 0.2]},
        ]
        with self.visits.open("a", encoding="utf-8") as handle:
            for event in legacy:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")

        frames = [
            make_obs(player=(0.1, 0.1)),        # A
            make_obs(player=None, dark=True),   # 黑屏
            make_obs(player=(0.2, 0.2)),        # 名字解析失败（模板 + OCR 都空）
            make_obs(player=(0.3, 0.3)),        # 下一张图也不能跨过空 id 记边
        ]
        self.feed(frames, names=["A", "", "C"])
        for _ in range(4):
            self.assertIsNone(watcher.step(object()))

        self.assertEqual(watcher.events, [])
        self.assertEqual(frames[2].map_id, "")          # 不是"未知地图"，也不是指纹
        self.assertEqual(len(self.read_events()), 3)    # 只有预置的脏数据，无新事件

        report = watcher.report()
        self.assertEqual(report["visits"], 0)
        self.assertEqual(report["maps"], [])
        self.assertEqual(report["edges"], [])
        payload = json.dumps(report, ensure_ascii=False)
        self.assertNotIn(mapwatch.LEGACY_UNKNOWN, payload)
        self.assertNotIn("c" * 100, payload)

    def test_d_unknown_player_is_not_origin(self):
        """找不到黄点 → player=None：不写 (0,0)、不聚类、不记边。"""
        # 1) observe 本身：没有候选时 player 必须是 None，不是 (0,0)
        frame = np.full((120, 200, 3), 50, np.uint8)
        box = minimap.MinimapBox(10, 10, 100, 40)
        with mock.patch.object(mapwatch.minimap, "find_minimap", return_value=box), \
                mock.patch.object(mapwatch.player, "find_candidates", return_value=[]):
            obs = mapwatch.observe(frame)
        self.assertIsNotNone(obs)
        self.assertIsNone(obs.player)
        self.assertEqual(obs.map_id, "")
        self.assertEqual(obs.size, (94, 34))
        # 每像素 1 字节再 hex：32 * 16 = 512 字节 = 1024 个字符
        self.assertEqual(len(obs.raw), mapwatch.FINGERPRINT[0] * mapwatch.FINGERPRINT[1] * 2)
        self.assertEqual(len(obs.raw), 1024)
        self.assertGreater(len(obs.raw), mapwatch.MAX_ID_LEN)

        # 2) 状态机：位置未知的过图直接跳过，seen_portals 里不能出现 (0,0)
        frames = [
            make_obs(player=(0.2, 0.3)),        # A
            make_obs(player=None),              # B，位置未知
            make_obs(player=(0.9, 0.9)),        # C，上一帧位置未知
        ]
        self.feed(frames, names=["A", "B", "C"])
        watcher = self.make_watcher()
        self.assertIsNone(watcher.step(object()))
        self.assertIsNone(watcher.step(object()))
        self.assertIsNone(watcher.step(object()))

        self.assertEqual(watcher.events, [])
        self.assertEqual(self.read_events(), [])
        self.assertEqual(watcher.seen_portals, {})
        self.assertNotIn((0.0, 0.0), watcher.seen_portals.get("A", set()))
        self.assertNotIn((0.0, 0.0), watcher.seen_portals.get("B", set()))
        self.assertNotIn("[0.0, 0.0]", json.dumps(watcher.report(), ensure_ascii=False))

        # 旧数据里的 (0,0) 哨兵也不能在报告里变成"未跑传送门"
        watcher.seen_portals["A"] = {(0.0, 0.0)}
        self.assertEqual(watcher.report()["unexplored"], [])


class ClusterAndKeyTest(MapWatchTestBase):
    def test_e_portal_cluster_pixel_radius_and_stable_key(self):
        """按 5px 聚类、命中后 key 稳定、explored/unexplored 用同一个 pos_key。"""
        watcher = self.make_watcher()
        size = (165, 48)

        key_a = watcher.cluster("A", (0.50, 0.50), size)
        self.assertEqual(key_a, mapwatch.pos_key((0.50, 0.50)))
        # Y 差 2px（0.0417 > 旧的 0.03 归一化半径）必须吸附到同一个门
        key_jitter = watcher.cluster("A", (0.50 + 2 / 165, 0.50 + 2 / 48), size)
        self.assertEqual(key_jitter, key_a)
        # X 差 20px 是另一个门
        key_far = watcher.cluster("A", (0.50 + 20 / 165, 0.50), size)
        self.assertNotEqual(key_far, key_a)

        # 反复抖动不会在桶里造新成员，返回的 key 也不变
        before = len(watcher.portal_points["A"])
        for i in range(20):
            got = watcher.cluster("A", (0.50 + (i % 3) / 165, 0.50), size)
            self.assertEqual(got, key_a)
        self.assertEqual(len(watcher.portal_points["A"]), before)

        # explored 存 pos_key：同一位置的小数抖动不能再被算成"未跑"
        watcher.seen_portals["A"] = {key_a}
        watcher.explored.add(("A", mapwatch.pos_key((0.50001, 0.49999))))
        self.assertEqual(watcher.report()["unexplored"], [])

        # 单图簇数上限：超出丢弃最近的重复项
        for i in range(13):
            watcher.cluster("B", (0.05 + i * 0.07, 0.5), size)
        self.assertLessEqual(len(watcher.portal_points["B"]), mapwatch.MAX_PORTALS)


class ToleranceTest(MapWatchTestBase):
    def test_f_corrupt_files_and_bad_visits_are_tolerated(self):
        """坏 jsonl 行跳过计数；损坏的 seen_portals 改 .bak；原子写；_Tee 接口。"""
        # 1) 坏行跳过并计数，好行照常恢复进度
        self.visits.parent.mkdir(parents=True, exist_ok=True)
        good = {"from_map": "A", "from_pos": [0.2, 0.3],
                "to_map": "B", "to_pos": [0.7, 0.8], "load_ms": 100}
        self.visits.write_text(
            "\n".join([json.dumps(good, ensure_ascii=False), "{坏行", "[1, 2]"]) + "\n",
            encoding="utf-8",
        )
        watcher = self.make_watcher()
        self.assertEqual(watcher.skipped_lines, 2)
        self.assertEqual(len(watcher.load_visits()), 1)
        self.assertEqual(watcher.skipped_lines, 2)
        self.assertIn("A", watcher.seen_portals)
        self.assertIn("B", watcher.seen_portals)
        self.assertEqual(len(watcher.report()["edges"]), 1)

        # 2) seen_portals.json 损坏：改名 .bak 并提示，不静默清空
        self.visits.unlink()
        self.portals.parent.mkdir(parents=True, exist_ok=True)
        self.portals.write_text("{坏掉的 json", encoding="utf-8")
        watcher = self.make_watcher()
        backup = self.portals.with_name(self.portals.name + ".bak")
        self.assertTrue(backup.exists())
        self.assertFalse(self.portals.exists())
        self.assertEqual(watcher.errors, [])

        # 3) 原子写：临时文件 + os.replace，结束后没有 .tmp 残留
        watcher.seen_portals.setdefault("C", set()).add(mapwatch.pos_key((0.4, 0.5)))
        watcher._flush_portals()
        self.assertTrue(self.portals.exists())
        saved = json.loads(self.portals.read_text(encoding="utf-8"))
        self.assertEqual(saved["C"], [[0.4, 0.5]])
        self.assertFalse(self.portals.with_name(self.portals.name + ".tmp").exists())

        # 4) _Tee 补齐 encoding / fileno / isatty（第三方库会调用）
        log_path = self.tmp / "tee.log"
        with log_path.open("a", encoding="utf-8") as handle:
            tee = mapwatch._Tee(handle)
            self.assertEqual(tee.encoding, "utf-8")
            self.assertIsInstance(tee.fileno(), int)
            self.assertFalse(tee.isatty())
            self.assertEqual(tee.write("hello"), 5)
            tee.flush()
        self.assertEqual(log_path.read_text(encoding="utf-8"), "hello")


if __name__ == "__main__":
    unittest.main()
