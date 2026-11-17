"""``maplebot.mapwatch`` 的合成帧单元测试（不碰真实游戏窗口 / PaddleOCR）。

覆盖这次重构的要点：

1. **单一过图判定**：前后两次"有名字"的观测地图名不一样就是一次过图，黑屏
   只用来量 ``load_ms``；空名字帧既不能自己成边，也不能吞掉前后两张图的配对；
2. 地图名统一由 ``step()`` 解析（模板 -> OCR + 纠错），指纹只能留在
   ``Observation.raw``，绝不会变成 ``map_id``；
3. 玩家位置未知时事件仍然记录：能测的一侧照常写坐标，测不到的一侧写 ``None``，
   绝不写 ``(0, 0)``；
4. ``explored`` / ``unexplored`` 用同一个 ``pos_key``，到达过的传送门也算已知；
5. 影响地图记录的异常（3 秒读不出名字 / 3 秒找不到小地图 / 换图丢边 /
   位置丢失 / 黑屏 30 秒 / 写盘失败 / observe 与名字解析抛异常）必须打印
   ``！！！！！`` 开头的告警，同一原因 60 秒内不重复刷屏；
6. 坏 jsonl 行、损坏的 seen_portals.json、``_Tee`` 的文件接口都有容错。

所有落盘路径都来自 ``tempfile.mkdtemp()``，不会写进项目 ``data/``。
"""

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

from maplebot import mapwatch, minimap

def _load_frame(path):
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)




def load(path):
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


#: 真实小地图名（``KNOWN_EXTRA`` 白名单内，``plausible_name`` 必须放行；
#: "A"/"B"/"C" 这种短名会被当成噪声丢弃）
MAP_A = "貿易地帶岔道"
MAP_B = "寂寞的沙漠-1"
MAP_C = "豐饒的沙漠-1"
MAP_D = "仙人掌沙漠-1"
MAP_E = "地下捷徑-1"
MAP_F = "納希貿易區-1"


def make_obs(raw="", player=(0.5, 0.5), size=(165, 48), dark=False, portals=()):
    """造一帧 Observation（map_id 故意留空，交给 step 解析）。"""
    return mapwatch.Observation(raw=raw, player=player, size=size, dark=dark,
                                portals=list(portals))


def alarm_lines(text):
    """从捕获的输出里挑出告警行（异常必须一眼能认出来）。"""
    return [line for line in text.splitlines()
            if line.startswith(mapwatch.ALARM_PREFIX)]


class MapWatchTestBase(unittest.TestCase):
    """公共夹具：tmp 路径 + monkeypatch 掉观察/命名/OCR 依赖。"""

    def setUp(self):
        # 名字缓存是模块级的：合成用例共用同一张裁剪图，不清会互相污染
        mapwatch._CROP_NAMES.clear()
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
                return self._names.pop(0), 0.99, 0.5
            return "", 0.0, 0.0

        patches = [
            # 名字截图区域：给一块合成图，避免依赖真实小地图。
            # 每帧换成不同内容——真实场景里换图时裁剪图本来就会变，
            # 用固定图会让"同一张图 = 同一个名字"的缓存把脚本名字吃掉。
            mock.patch.object(mapwatch, "name_crop", side_effect=self._name_crop),
            mock.patch.object(mapwatch, "match_name", side_effect=fake_match),
            # 绝不启用 PaddleOCR（连实例都不造）
            mock.patch.object(mapwatch, "read_map_name", return_value=("", "")),
            mock.patch.object(mapwatch.MapWatcher, "_ocr_instance", return_value=object()),
            # 模板落盘会写项目 data/，测试里直接吞掉
            mock.patch.object(mapwatch, "save_name_template"),
            # 合成用例里的地图名不在基准图里，别让"未知边"告警干扰断言
            mock.patch.object(mapwatch, "load_baseline", return_value=set()),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _name_crop(self, frame=None, scale=None):
        self._crop_seq = getattr(self, "_crop_seq", 0) + 1
        return np.full((40, 160, 3), self._crop_seq % 251, np.uint8)

    def make_watcher(self):
        watcher = mapwatch.MapWatcher(
            visits_path=str(self.visits),
            portals_path=str(self.portals),
            names_path=str(self.names),
        )
        watcher.startup_grace = 0.0      # 测试不要启动宽限期，否则前 10 秒不报警
        return watcher

    def feed(self, frames, names=()):
        """让 observe 按顺序返回 frames；match_name 按顺序返回 names。"""
        self._script = list(frames)
        self._names = list(names)

        def fake_observe(frame, **kwargs):
            return self._script.pop(0) if self._script else None

        patcher = mock.patch.object(mapwatch, "observe", side_effect=fake_observe)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_steps(self, steps):
        """按 ``(obs, name, now)`` 跑一串帧，返回 ``(watcher, events, 告警行)``。

        黑屏帧不解析名字，它的 ``name`` 必须是 ``None``；``now=None`` 表示用真实时钟。
        """
        frames = []
        names = []
        for obs, name, _now in steps:
            frames.append(obs)
            if obs.dark:
                if name is not None:
                    raise AssertionError("黑屏帧不该消费名字")
                continue
            if name is None:
                raise AssertionError("非黑屏帧必须给名字（空串表示解析失败）")
            names.append(name)
        self.feed(frames, names)
        watcher = self.make_watcher()
        buffer = io.StringIO()
        events = []
        with contextlib.redirect_stdout(buffer):
            for _obs, _name, now in steps:
                event = watcher.step(object(), now=now)
                if event is not None:
                    events.append(event)
        return watcher, events, alarm_lines(buffer.getvalue())

    def read_events(self):
        if not self.visits.exists():
            return []
        return [json.loads(line) for line in
                self.visits.read_text(encoding="utf-8").splitlines() if line.strip()]


class NameAndEdgeTest(MapWatchTestBase):
    def test_a_dark_transition_uses_names_not_fingerprint(self):
        """貿易地帶岔道 → 黑屏 → 寂寞的沙漠-1：1 条事件，id 是名字不是指纹。"""
        raw_a = "a" * 1024      # 模拟旧版本 1024 字符指纹
        raw_b = "b" * 1024
        steps = [
            (make_obs(raw=raw_a, player=(0.2, 0.3)), MAP_A, 1.0),
            (make_obs(raw="", player=None, dark=True), None, 1.5),
            (make_obs(raw=raw_b, player=(0.8, 0.7)), MAP_B, 2.0),
        ]
        watcher, events, lines = self.run_steps(steps)
        self.assertEqual(lines, [])
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["from_map"], MAP_A)
        self.assertEqual(event["to_map"], MAP_B)
        self.assertEqual(event["from_pos"], [0.2, 0.3])
        self.assertEqual(event["to_pos"], [0.8, 0.7])
        self.assertEqual(event["load_ms"], 500.0)      # 黑屏 1.5s -> 2.0s

        # 到达过的传送门也算"已确认"：B 的落点同时进 seen_portals / explored
        arrived = mapwatch.pos_key((0.8, 0.7))
        self.assertEqual(watcher.seen_portals[MAP_B], {arrived})
        self.assertIn((MAP_B, arrived), watcher.explored)
        self.assertIn((MAP_A, mapwatch.pos_key((0.2, 0.3))), watcher.explored)

        saved = self.read_events()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["from_map"], MAP_A)
        self.assertEqual(saved[0]["to_map"], MAP_B)
        for key in ("from_map", "to_map"):
            self.assertLessEqual(len(saved[0][key]), mapwatch.MAX_ID_LEN)
            self.assertNotEqual(saved[0][key], raw_a)
            self.assertNotEqual(saved[0][key], raw_b)
        for value in saved[0].values():
            self.assertNotEqual(value, raw_a)
            self.assertNotEqual(value, raw_b)

        # 指纹只留在 raw，step 解析后的 map_id 是名字
        frames = [obs for obs, _name, _now in steps]
        self.assertEqual(frames[0].raw, raw_a)
        self.assertEqual(frames[0].map_id, MAP_A)
        self.assertEqual(frames[2].map_id, MAP_B)

        report = watcher.report()
        self.assertEqual({item["id"] for item in report["maps"]}, {MAP_A, MAP_B})
        self.assertEqual(len(report["edges"]), 1)

    def test_b_round_trip_no_dark_edges_and_unexplored(self):
        """A → B → A → B（不黑屏）：maps=2、两条有向边、未跑不再增长。"""
        frames = [
            make_obs(player=(0.1, 0.2)),
            make_obs(player=(0.6, 0.7)),
            make_obs(player=(0.1, 0.2)),
            make_obs(player=(0.6, 0.7)),
        ]
        self.feed(frames, names=[MAP_A, MAP_B, MAP_A, MAP_B])
        watcher = self.make_watcher()

        self.assertIsNone(watcher.step(object(), now=0.0))   # 进场 A
        first = watcher.step(object(), now=1.0)
        self.assertEqual((first["from_map"], first["to_map"]), (MAP_A, MAP_B))
        # 没有黑屏：load_ms 必须是 None，而不是 0 / 假值
        self.assertIsNone(first["load_ms"])
        # 到达的传送门也算已知（与 _replay 的"到达过也算已知"一致）
        self.assertEqual(len(watcher.report()["unexplored"]), 0)

        second = watcher.step(object(), now=2.0)             # 一次往返
        self.assertEqual((second["from_map"], second["to_map"]), (MAP_B, MAP_A))
        after_round_trip = len(watcher.report()["unexplored"])
        self.assertEqual(after_round_trip, 0)

        third = watcher.step(object(), now=3.0)              # 再走一次
        self.assertEqual((third["from_map"], third["to_map"]), (MAP_A, MAP_B))
        self.assertEqual(len(watcher.report()["unexplored"]), after_round_trip)

        report = watcher.report()
        self.assertEqual(len(report["maps"]), 2)
        self.assertEqual(len(report["edges"]), 2)
        edges = {(item["from"], item["to"]): item["count"] for item in report["edges"]}
        self.assertEqual(edges, {(MAP_A, MAP_B): 2, (MAP_B, MAP_A): 1})

    def test_c_name_failure_records_nothing(self):
        """名字解析失败：不产生事件，报告里也没有空 id / 旧占位符 / 指纹。"""
        watcher = self.make_watcher()          # 先建，避免预置脏数据被 _replay 吃掉
        self.visits.parent.mkdir(parents=True, exist_ok=True)
        legacy = [
            {"from_map": MAP_A, "from_pos": [0.1, 0.1],
             "to_map": "", "to_pos": [0.2, 0.2]},
            {"from_map": MAP_A, "from_pos": [0.1, 0.1],
             "to_map": mapwatch.LEGACY_UNKNOWN, "to_pos": [0.2, 0.2]},
            {"from_map": "c" * 1024, "from_pos": [0.1, 0.1],
             "to_map": MAP_B, "to_pos": [0.2, 0.2]},
        ]
        with self.visits.open("a", encoding="utf-8") as handle:
            for event in legacy:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")

        frames = [
            make_obs(player=(0.1, 0.1)),        # A
            make_obs(player=None, dark=True),   # 黑屏
            make_obs(player=(0.2, 0.2)),        # 名字解析失败（模板 + OCR 都空）
        ]
        self.feed(frames, names=[MAP_A, ""])
        for _ in range(3):
            event = watcher.step(object(), now=None)
            if event is not None:
                # 关键：空名字那一帧不能自己成一条边
                self.assertTrue(event["from_map"] and event["to_map"])

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
        """找不到黄点 → player=None：事件仍记录，测不到的一侧是 None，绝不写 (0,0)。"""
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

        # 2) 状态机：位置未知也要记录过图（否则丢地图连接），能测的一侧照常写
        frames = [
            make_obs(player=(0.2, 0.3)),        # A
            make_obs(player=None),              # B，到达位置未知
            make_obs(player=(0.9, 0.9)),        # C，出发位置未知
        ]
        self.feed(frames, names=[MAP_A, MAP_B, MAP_C])
        watcher = self.make_watcher()
        self.assertIsNone(watcher.step(object(), now=0.0))      # A：只建立配对基准

        # A -> B：到达位置未知，事件仍要记录；出发位置是量到的，不能一起丢
        first = watcher.step(object(), now=1.0)
        self.assertIsNotNone(first)
        self.assertEqual((first["from_map"], first["to_map"]), (MAP_A, MAP_B))
        self.assertEqual(first["from_pos"], [0.2, 0.3])
        self.assertIsNone(first["to_pos"])

        # B -> C：出发位置未知，同样只缺坐标
        second = watcher.step(object(), now=2.0)
        self.assertIsNotNone(second)
        self.assertEqual((second["from_map"], second["to_map"]), (MAP_B, MAP_C))
        self.assertIsNone(second["from_pos"])
        self.assertEqual(second["to_pos"], [0.9, 0.9])

        # 两条事件都落了盘，且没有任何坐标落成 (0,0) 哨兵
        self.assertEqual(watcher.events, [first, second])
        self.assertEqual([(e["from_map"], e["to_map"]) for e in self.read_events()],
                         [(MAP_A, MAP_B), (MAP_B, MAP_C)])
        self.assertEqual(watcher.seen_portals, {
            MAP_A: {mapwatch.pos_key((0.2, 0.3))},
            MAP_C: {mapwatch.pos_key((0.9, 0.9))},
        })
        self.assertNotIn(MAP_B, watcher.seen_portals)   # 两侧都缺时不凭空造位置
        for positions in watcher.seen_portals.values():
            self.assertNotIn((0.0, 0.0), positions)
        self.assertNotIn("[0.0, 0.0]", json.dumps(watcher.report(), ensure_ascii=False))
        self.assertNotIn("0.0, 0.0", json.dumps(watcher.events, ensure_ascii=False))

        # 旧数据里的 (0,0) 哨兵也不能在报告里变成"未跑传送门"
        watcher.seen_portals[MAP_A] = {(0.0, 0.0)}
        self.assertEqual(watcher.report()["unexplored"], [])

    def test_g_five_transitions_with_blank_and_dark_frames(self):
        """A：连续 5 次换图（穿插空名字 / 黑屏）→ 恰好 5 条，顺序正确。"""
        steps = [
            (make_obs(player=(0.10, 0.10)), MAP_A, 0.0),
            (make_obs(player=(0.15, 0.15)), "", 0.5),        # 空名字帧
            (make_obs(player=None, dark=True), None, 0.6),   # 黑屏
            (make_obs(player=(0.20, 0.20)), MAP_B, 1.1),
            (make_obs(player=(0.30, 0.30)), MAP_C, 1.6),     # 不黑屏也换图
            (make_obs(player=None, dark=True), None, 1.7),
            (make_obs(player=(0.35, 0.35)), "", 2.2),        # 黑屏后名字先空一帧
            (make_obs(player=(0.40, 0.40)), MAP_D, 2.7),
            (make_obs(player=(0.50, 0.50)), MAP_E, 3.2),
            (make_obs(player=None, dark=True), None, 3.3),
            (make_obs(player=(0.60, 0.60)), MAP_F, 3.8),
        ]
        watcher, events, lines = self.run_steps(steps)
        self.assertEqual(lines, [])       # 这些情况都不该报警
        self.assertEqual([(e["from_map"], e["to_map"]) for e in events],
                         [(MAP_A, MAP_B), (MAP_B, MAP_C), (MAP_C, MAP_D),
                          (MAP_D, MAP_E), (MAP_E, MAP_F)])
        # A→B、C→D、E→F 前有黑屏 → load_ms 有值；B→C、D→E 没有 → None
        self.assertEqual([e["load_ms"] for e in events],
                         [500.0, None, 500.0, None, 500.0])
        # 空名字帧不会自己成边
        self.assertEqual(len(self.read_events()), 5)
        self.assertEqual([(e["from_map"], e["to_map"]) for e in self.read_events()],
                         [(e["from_map"], e["to_map"]) for e in events])
        self.assertEqual(watcher.alarm_count, 0)

    def test_h_blank_frame_does_not_swallow_pairing(self):
        """B：A → 空名字帧 → C 仍要记 A -> C；空帧自己不成边。"""
        steps = [
            (make_obs(player=(0.1, 0.1)), MAP_A, 100.0),
            (make_obs(player=(0.2, 0.2)), "", 100.2),
            (make_obs(player=(0.3, 0.3)), "", 100.4),
            (make_obs(player=(0.4, 0.4)), MAP_C, 100.6),
        ]
        watcher, events, lines = self.run_steps(steps)
        self.assertEqual(lines, [])
        self.assertEqual([(e["from_map"], e["to_map"]) for e in events], [(MAP_A, MAP_C)])
        self.assertEqual(events[0]["from_pos"], [0.1, 0.1])
        self.assertEqual(events[0]["to_pos"], [0.4, 0.4])
        self.assertEqual(len(watcher.events), 1)


class NameTemplateStorageTest(unittest.TestCase):
    """模板落盘：基准尺寸进平铺目录，其他分辨率进各自子目录。

    踩过的坑：把 1920 缩小后的裁剪也当成 240x44 存进 240x44/ 子目录，
    加载时它盖住了原本清晰的 1366 模板，导致 9 张图在 1366 下认不出来。
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mapwatch-names-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.names_dir = self.tmp / "map_names"
        patcher = mock.patch.object(mapwatch, "NAMES_DIR", self.names_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self._saved = mapwatch._name_templates
        mapwatch._name_templates = None
        self.addCleanup(self._restore)

    def _restore(self):
        mapwatch._name_templates = self._saved

    def test_canonical_crop_goes_to_the_flat_directory(self):
        crop = np.zeros((44, 240, 3), np.uint8)
        crop[:] = 17
        self.assertTrue(mapwatch.save_name_template("測試圖", crop))
        self.assertTrue((self.names_dir / "測試圖.png").exists())
        self.assertFalse((self.names_dir / "240x44").exists())

    def test_other_size_crop_goes_to_its_own_subdirectory(self):
        crop = np.zeros((62, 337, 3), np.uint8)
        crop[:] = 23
        self.assertTrue(mapwatch.save_name_template("測試圖1920", crop))
        self.assertTrue((self.names_dir / "337x62" / "測試圖1920.png").exists())
        self.assertFalse((self.names_dir / "測試圖1920.png").exists())

    def test_canonical_templates_ignore_other_sizes(self):
        small = np.zeros((44, 240, 3), np.uint8)
        big = np.zeros((62, 337, 3), np.uint8)
        mapwatch.save_name_template("小的", small)
        mapwatch.save_name_template("大的", big)
        table = mapwatch.load_name_templates_for((44, 240))
        self.assertIn("小的", table)
        self.assertNotIn("大的", table)

    def test_existing_template_is_never_overwritten(self):
        first = np.zeros((44, 240, 3), np.uint8)
        first[:] = 5
        self.assertTrue(mapwatch.save_name_template("測試圖", first))
        second = np.zeros((44, 240, 3), np.uint8)
        second[:] = 200
        self.assertFalse(mapwatch.save_name_template("測試圖", second))
        loaded = mapwatch.load_name_templates_for((44, 240))["測試圖"]
        self.assertEqual(int(loaded[0, 0, 0]), 5)


class AlarmTest(MapWatchTestBase):
    """需求 2：影响地图记录的异常必须立刻打印 ``！！！！！`` 告警。"""

    def test_j_blank_name_for_three_seconds_alarms_once(self):
        """D：名字连续空 3 秒 → 告警；60 秒内同一原因不重复刷屏。"""
        steps = [(make_obs(player=(0.5, 0.5)), "", now)
                 for now in (100.0, 101.0, 102.0, 103.0, 103.5, 104.0)]
        watcher, events, lines = self.run_steps(steps)
        self.assertEqual(events, [])
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("！！！！！ 地图记录异常："))
        self.assertIn("解析不出地图名", lines[0])
        self.assertTrue(lines[0].endswith("，请暂停跑图并通知开发者"))
        self.assertEqual(watcher.alarm_count, 1)
        self.assertEqual([item["code"] for item in watcher.alarms], ["blank_name"])

    def test_k_same_alarm_repeats_after_sixty_seconds(self):
        """同一原因：首次之后每 60 秒才报一次，中间不刷屏。"""
        steps = [(make_obs(player=(0.5, 0.5)), "", now)
                 for now in (100.0, 103.0, 104.0, 130.0, 170.0)]
        watcher, events, lines = self.run_steps(steps)
        self.assertEqual(events, [])
        self.assertEqual(len(lines), 2)      # 103s 首次 / 170s 超过 60 秒再报
        self.assertEqual(watcher.alarm_count, 2)
        self.assertEqual({item["code"] for item in watcher.alarms}, {"blank_name"})

    def test_l_no_minimap_for_three_seconds_alarms(self):
        """连续 3 秒找不到小地图（被遮挡 / 不在跑商地图）→ 告警。"""
        steps = [(make_obs(player=None, size=(0, 0)), "", now)
                 for now in (0.0, 1.0, 2.0, 3.0, 3.5)]
        watcher, events, lines = self.run_steps(steps)
        self.assertEqual(events, [])
        self.assertEqual(len(lines), 1)
        self.assertIn("找不到小地图", lines[0])
        self.assertEqual([item["code"] for item in watcher.alarms], ["no_minimap"])

    def test_m_dark_over_thirty_seconds_alarms(self):
        """黑屏超过 30 秒（可能卡在加载）→ 告警。"""
        steps = [(make_obs(player=None, dark=True), None, now)
                 for now in (0.0, 10.0, 30.0, 30.5, 40.0)]
        watcher, events, lines = self.run_steps(steps)
        self.assertEqual(events, [])
        self.assertEqual(len(lines), 1)
        self.assertIn("黑屏", lines[0])
        self.assertEqual([item["code"] for item in watcher.alarms], ["dark"])

    def test_n_dark_before_any_name_alarms_lost_edge(self):
        """换图时出发侧地图名不可用（进黑屏前就不知道在哪）→ 告警。"""
        steps = [
            (make_obs(player=None, dark=True), None, 0.0),
            (make_obs(player=(0.5, 0.5)), MAP_A, 1.0),
            (make_obs(player=(0.6, 0.6)), MAP_B, 2.0),
        ]
        watcher, events, lines = self.run_steps(steps)
        self.assertEqual(len(lines), 1)
        self.assertIn("出发侧地图名不可用", lines[0])
        self.assertEqual([item["code"] for item in watcher.alarms], ["lost_from"])
        # 之后恢复正常：A -> B 照常记录
        self.assertEqual([(e["from_map"], e["to_map"]) for e in events], [(MAP_A, MAP_B)])

    def test_o_write_failure_alarms_without_crash(self):
        """E：写 jsonl / seen_portals 失败 → 告警，step 不崩，恢复后继续记。"""
        frames = [
            make_obs(player=(0.1, 0.1)),
            make_obs(player=(0.2, 0.2)),
            make_obs(player=(0.3, 0.3)),
        ]
        self.feed(frames, names=[MAP_A, MAP_B, MAP_C])
        watcher = self.make_watcher()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertIsNone(watcher.step(object(), now=0.0))
            with mock.patch.object(Path, "open", side_effect=OSError("磁盘已满")):
                failed = watcher.step(object(), now=1.0)
                self.assertIsNotNone(failed)      # 事件仍在内存里，采集不崩
                self.assertEqual((failed["from_map"], failed["to_map"]), (MAP_A, MAP_B))
            # 磁盘恢复后继续记录，不会因为一次失败就不再干活
            third = watcher.step(object(), now=2.0)
            self.assertEqual((third["from_map"], third["to_map"]), (MAP_B, MAP_C))

        lines = alarm_lines(buffer.getvalue())
        self.assertGreaterEqual(len(lines), 2)
        self.assertTrue(all(line.startswith("！！！！！ 地图记录异常：") for line in lines))
        self.assertTrue(all("写" in line for line in lines))
        codes = {item["code"] for item in watcher.alarms}
        self.assertIn("write_visits", codes)
        self.assertIn("write_portals", codes)
        self.assertGreaterEqual(watcher.alarm_count, 2)
        # 只有恢复后的那次落盘成功
        self.assertEqual([(e["from_map"], e["to_map"]) for e in self.read_events()],
                         [(MAP_B, MAP_C)])

    def test_p_missing_position_alarms_but_still_records(self):
        """换图时玩家位置不可用 → 降级记录并告警（两侧各自判断）。"""
        steps = [
            (make_obs(player=(0.2, 0.3)), MAP_A, 0.0),
            (make_obs(player=None), MAP_B, 1.0),
            (make_obs(player=(0.9, 0.9)), MAP_C, 100.0),   # >60 秒，允许再次告警
        ]
        watcher, events, lines = self.run_steps(steps)
        self.assertEqual(len(events), 2)
        self.assertIsNone(events[0]["to_pos"])
        self.assertIsNone(events[1]["from_pos"])
        # 位置缺失是常态（角色站在传送门上），只降级提示，不能报 ！！！！！ 告警
        self.assertEqual(lines, [])          # run_steps 收集的是告警行，这里必须为空
        self.assertEqual(watcher.alarm_count, 0)

    def test_q_observe_exception_alarms(self):
        """observe() 抛异常 → 告警且不会把采集循环打死。"""
        watcher = self.make_watcher()
        buffer = io.StringIO()

        def boom(frame):
            raise RuntimeError("抓帧失败")

        with contextlib.redirect_stdout(buffer), \
                mock.patch.object(mapwatch, "observe", side_effect=boom):
            self.assertIsNone(watcher.step(object(), now=0.0))
        lines = alarm_lines(buffer.getvalue())
        self.assertEqual(len(lines), 1)
        self.assertIn("observe() 抛异常", lines[0])
        self.assertEqual([item["code"] for item in watcher.alarms], ["observe"])
        self.assertTrue(any("observe" in error for error in watcher.errors))

    def test_r_name_resolution_exception_alarms(self):
        """名字解析（模板匹配）抛异常 → 告警，这一帧按"没名字"处理。"""
        watcher = self.make_watcher()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), \
                mock.patch.object(mapwatch, "observe",
                                  return_value=make_obs(player=(0.5, 0.5))), \
                mock.patch.object(mapwatch, "match_name",
                                  side_effect=RuntimeError("模板损坏")), \
                mock.patch.object(mapwatch.minimap, "find_minimap", return_value=None):
            self.assertIsNone(watcher.step(object(), now=0.0))
        lines = alarm_lines(buffer.getvalue())
        self.assertEqual(len(lines), 1)
        self.assertIn("模板匹配抛异常", lines[0])
        self.assertEqual({item["code"] for item in watcher.alarms}, {"name_match"})


class ClusterAndKeyTest(MapWatchTestBase):
    def test_e_portal_cluster_pixel_radius_and_stable_key(self):
        """按 5px 聚类、命中后 key 稳定、explored/unexplored 用同一个 pos_key。"""
        watcher = self.make_watcher()
        size = (165, 48)

        key_a = watcher.cluster(MAP_A, (0.50, 0.50), size)
        self.assertEqual(key_a, mapwatch.pos_key((0.50, 0.50)))
        # Y 差 2px（0.0417 > 旧的 0.03 归一化半径）必须吸附到同一个门
        key_jitter = watcher.cluster(MAP_A, (0.50 + 2 / 165, 0.50 + 2 / 48), size)
        self.assertEqual(key_jitter, key_a)
        # X 差 20px 是另一个门
        key_far = watcher.cluster(MAP_A, (0.50 + 20 / 165, 0.50), size)
        self.assertNotEqual(key_far, key_a)

        # 反复抖动不会在桶里造新成员，返回的 key 也不变
        before = len(watcher.portal_points[MAP_A])
        for i in range(20):
            got = watcher.cluster(MAP_A, (0.50 + (i % 3) / 165, 0.50), size)
            self.assertEqual(got, key_a)
        self.assertEqual(len(watcher.portal_points[MAP_A]), before)

        # explored 存 pos_key：同一位置的小数抖动不能再被算成"未跑"
        watcher.seen_portals[MAP_A] = {key_a}
        watcher.explored.add((MAP_A, mapwatch.pos_key((0.50001, 0.49999))))
        self.assertEqual(watcher.report()["unexplored"], [])

        # 单图簇数上限：超出丢弃最近的重复项
        for i in range(13):
            watcher.cluster(MAP_B, (0.05 + i * 0.07, 0.5), size)
        self.assertLessEqual(len(watcher.portal_points[MAP_B]), mapwatch.MAX_PORTALS)


class ToleranceTest(MapWatchTestBase):
    def test_f_corrupt_files_and_bad_visits_are_tolerated(self):
        """坏 jsonl 行跳过计数；损坏的 seen_portals 改 .bak；原子写；_Tee 接口。"""
        # 1) 坏行跳过并计数，好行照常恢复进度
        self.visits.parent.mkdir(parents=True, exist_ok=True)
        good = {"from_map": MAP_A, "from_pos": [0.2, 0.3],
                "to_map": MAP_B, "to_pos": [0.7, 0.8], "load_ms": 100}
        self.visits.write_text(
            "\n".join([json.dumps(good, ensure_ascii=False), "{坏行", "[1, 2]"]) + "\n",
            encoding="utf-8",
        )
        watcher = self.make_watcher()
        self.assertEqual(watcher.skipped_lines, 2)
        self.assertEqual(len(watcher.load_visits()), 1)
        self.assertEqual(watcher.skipped_lines, 2)
        self.assertIn(MAP_A, watcher.seen_portals)
        self.assertIn(MAP_B, watcher.seen_portals)
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
        watcher.seen_portals.setdefault(MAP_C, set()).add(mapwatch.pos_key((0.4, 0.5)))
        watcher._flush_portals()
        self.assertTrue(self.portals.exists())
        saved = json.loads(self.portals.read_text(encoding="utf-8"))
        self.assertEqual(saved[MAP_C], [[0.4, 0.5]])
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

class ShopDwellTest(unittest.TestCase):
    """逛商店的时间不该算进跑图耗时；首次开商店要记"门→商人"样本。"""

    def test_dwell_is_excluded_from_sample(self):
        import json, tempfile
        from maplebot import mapwatch
        watcher = mapwatch.MapWatcher()
        watcher._arrival_ts = 100.0
        tmp = Path(tempfile.mkdtemp()) / "raw.jsonl"
        orig = mapwatch.EDGE_RAW_PATH
        mapwatch.EDGE_RAW_PATH = tmp
        try:
            watcher.note_shop(110.0, True)      # 开商店
            watcher.note_shop(130.0, False)     # 关：逛了 20 秒
            event = {"from_map": "A", "to_map": "B", "load_ms": 0,
                     "from_pos": [0.1, 0.2], "to_pos": [0.8, 0.9]}
            watcher._record_time_sample(event, now=140.0)
        finally:
            mapwatch.EDGE_RAW_PATH = orig
        rows = [json.loads(l) for l in tmp.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 1)
        # 140 - 100 - 20(逛店) = 20
        self.assertAlmostEqual(rows[0]["seconds"], 20.0, places=2)

    def test_note_shop_tracks_dwell(self):
        from maplebot import mapwatch
        watcher = mapwatch.MapWatcher.__new__(mapwatch.MapWatcher)
        mapwatch.MapWatcher.__init__(watcher)
        watcher._arrival_ts = 100.0
        watcher.note_shop(110.0, True)
        watcher.note_shop(135.0, False)
        self.assertAlmostEqual(watcher._shop_dwell, 25.0, places=3)

class NameTemplateRobustnessTest(unittest.TestCase):
    """模板对亮度和对比度不敏感，且同前缀 -1/-2/-3 之间不会互相认错。

    背景：早期模板和实时画面亮度差 40 个灰度，用"差异像素"判据会把正确模板
    拒掉（610 个像素被判不同），于是掉进 OCR 兜底、把地图认成隔壁那张。
    """

    @staticmethod
    def _perturb(img, bright=0, contrast=1.0, blur=0.0):
        out = np.clip(img.astype(np.float32) * contrast + bright, 0, 255).astype(np.uint8)
        if blur:
            out = cv2.GaussianBlur(out, (0, 0), blur)
        return out

    def test_every_template_identifies_itself(self):
        for shape in ((44, 240), (62, 337)):
            templates = mapwatch.load_name_templates_for(shape)
            self.assertGreater(len(templates), 20)
            for name, image in templates.items():
                got, best, second = mapwatch.match_name(image)
                self.assertEqual(got, name, f"形状 {shape} 的模板 {name} 认成了自己以外")
                self.assertGreaterEqual(best - second, 0.005)

    def test_brightness_and_contrast_do_not_break_matching(self):
        templates = mapwatch.load_name_templates()
        for name in ("孤獨的沙漠-3", "寂寞的沙漠-2", "豐饒的沙漠-1", "仙人掌沙漠-3"):
            image = templates[name]
            for kwargs in ({"bright": 40}, {"bright": -40}, {"contrast": 1.3},
                           {"contrast": 0.75}, {"blur": 0.5}):
                got, _best, _second = mapwatch.match_name(self._perturb(image, **kwargs))
                self.assertEqual(got, name, f"{name} 在 {kwargs} 之后认不出了")

    def test_prefix_siblings_are_not_confused(self):
        templates = mapwatch.load_name_templates()
        for name in ("豐饒的沙漠-1", "豐饒的沙漠-2", "豐饒的沙漠-3",
                     "孤獨的沙漠-1", "孤獨的沙漠-2", "孤獨的沙漠-3"):
            got, _best, _second = mapwatch.match_name(templates[name])
            self.assertEqual(got, name)

    def test_live_frame_is_recognised(self):
        path = Path(__file__).resolve().parent / "fixtures" / "map_name_gudu_1366.png"
        self.assertTrue(path.exists())
        frame = _load_frame(path)
        crop = mapwatch.name_crop(frame)
        self.assertIsNotNone(crop)
        got, _best, _second = mapwatch.match_name(crop)
        self.assertEqual(got, "孤獨的沙漠-3")

    def test_non_trade_map_is_rejected(self):
        path = Path(__file__).resolve().parent / "fixtures" / "map_name_archer_1366.png"
        self.assertTrue(path.exists())
        crop = mapwatch.name_crop(_load_frame(path))
        self.assertIsNotNone(crop)
        got, best, _second = mapwatch.match_name(crop)
        self.assertEqual(got, "", "非跑商地图不该被硬认成某张跑商图")
        self.assertLess(best, 0.5)

