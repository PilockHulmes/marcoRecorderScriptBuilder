"""跑商地图信息收集：小地图指纹 + 过图记录 + 传送门配对。

设计：
- **地图身份**用地图名：先和已存名字截图做模板匹配，再 OCR + 补字/换字纠错；
  形状指纹只放在 ``Observation.raw`` 里备用，**绝不**当 ``map_id``；
- **过图**判定 = 屏幕变黑 → 恢复后地图名变了；
- **出发传送门** = 黑屏前最后一帧的玩家位置（过图必须在传送门上）；
- **到达传送门** = 加载完成后玩家的位置（角色正站在传送门上，图标被挡住也能定位）；
- 坐标全部按小地图内容区归一化到 0~1。

用法::

    python -m maplebot.mapwatch --run            # 边玩边收集（Ctrl+C 结束）
    python -m maplebot.mapwatch --report          # 看已收集到的地图/连接
"""

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

import difflib

from . import minimap, player

ROOT = Path(__file__).resolve().parents[1]
VISITS_PATH = ROOT / "data" / "trade" / "map_visits.jsonl"
PORTALS_PATH = ROOT / "data" / "trade" / "seen_portals.json"
NAMES_DIR = ROOT / "data" / "trade" / "map_names"
NAME_THRESHOLD = 0.85
NAMES_PATH = ROOT / "data" / "trade" / "map_names.json"

#: 小地图图标颜色（实测：NPC 蓝点 H 85~110，传送门绿圈 H 40~80）
NPC_RANGE = ((85, 120, 120), (110, 255, 255))
PORTAL_TEMPLATE = ROOT / "data" / "trade" / "icons" / "portal.png"
PORTAL_THRESHOLD = 0.80
#: 全屏变黑判定：平均亮度低于这个值算 loading
DARK_MEAN = 40
#: 小地图指纹尺寸
FINGERPRINT = (32, 16)

#: 传送门聚类半径（小地图像素）：165x48 的小地图上 X/Y 都是 5px，
#: 避免纯归一化半径（X 5px、Y 1.4px）把同一个门裂成两个簇。
CLUSTER_PX = 5.0
#: 拿不到小地图尺寸时的退回归一化半径（旧数据 _replay 用）
CLUSTER_RX, CLUSTER_RY = 0.03, 0.10
#: 单张图最多登记多少个传送门簇，超出丢弃最近的重复项
MAX_PORTALS = 12
#: map_id（地图名）合理长度上限；指纹有上百字符，不能混进报告
MAX_ID_LEN = 60
#: 旧版本在没认出名字时写的占位 id；历史数据里可能有，报告里要忽略
LEGACY_UNKNOWN = "未知地图"


#: 旧版本找不到玩家黄点时写的哨兵坐标；新数据不会再有，读旧文件/报告时过滤
UNKNOWN_POS = (0.0, 0.0)


def pos_key(pos):
    """坐标落盘/比较用的稳定 key（4 位小数）。所有 add/查询都必须用它。"""
    return (round(pos[0], 4), round(pos[1], 4))


def usable_id(map_id):
    """这个 id 是否能当真实地图名用（排除空串/旧占位符/指纹）。"""
    map_id = str(map_id or "")
    return bool(map_id) and map_id != LEGACY_UNKNOWN and len(map_id) <= MAX_ID_LEN


def _as_pos(value):
    """把 jsonl 里的 [x, y] 解析成二元组；非法/缺省返回 None。"""
    try:
        if value is None or len(value) != 2:
            return None
        return (float(value[0]), float(value[1]))
    except (TypeError, ValueError):
        return None


_portal_template = None


def _match_portals(crop, template=None, threshold=PORTAL_THRESHOLD):
    """用模板找传送门绿圈（比颜色阈值干净：实测 1 个命中 0.95）。"""
    global _portal_template
    if template is None:
        if _portal_template is None:
            try:
                data = np.fromfile(str(PORTAL_TEMPLATE), dtype=np.uint8)
                _portal_template = cv2.imdecode(data, cv2.IMREAD_COLOR)
            except Exception:
                _portal_template = False
        template = _portal_template
    if template is False or template is None:
        return []
    if crop.shape[0] < template.shape[0] or crop.shape[1] < template.shape[1]:
        return []
    result = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(result >= threshold)
    out = []
    for x, y in zip(xs, ys):
        cx, cy = int(x) + template.shape[1] // 2, int(y) + template.shape[0] // 2
        if all((cx - px) ** 2 + (cy - py) ** 2 > 25 for px, py, _ in out):
            out.append((float(cx), float(cy), float(result[y, x])))
    return out


def _blobs(hsv, lo, hi, min_area=4, max_area=200):
    mask = cv2.inRange(hsv, np.array(lo), np.array(hi))
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if min_area <= area <= max_area:
            out.append((float(centroids[i][0]), float(centroids[i][1]), int(area)))
    return out


#: 人工/大地图确认过的小地图名（OCR 漏字时用来"补字"）
KNOWN_EXTRA = [
    "納希沙漠自由貿易地帶", "休菲凱曼的探險列車", "貿易地帶岔道", "通往納希貿易區的路", "通往古代遺跡的路",
    "豐饒的沙漠-1", "豐饒的沙漠-2", "豐饒的沙漠-3",
    "孤獨的沙漠-1", "孤獨的沙漠-2", "孤獨的沙漠-3",
    "寂寞的沙漠-1", "寂寞的沙漠-2", "寂寞的沙漠-3",
    "寂寞的沙漠捷徑-1", "寂寞的沙漠捷徑-2", "寂寞的沙漠捷徑-3",
    "仙人掌沙漠-1", "仙人掌沙漠-2", "仙人掌沙漠-3",
    "地下捷徑-1", "地下捷徑-2", "地下捷徑-3",
    "納希貿易區-1", "納希貿易區-2", "納希貿易區-3", "納希貿易區-4",
    "瑪迦提亞貿易區-1", "瑪迦提亞貿易區-2", "瑪迦提亞貿易區-3", "瑪迦提亞貿易區-4",
    "古代遺跡地內部-1", "古代遺跡地內部-2", "古代遺跡地內部-3", "古代遺跡地內部-4",
]


_name_templates = None


def load_name_templates():
    global _name_templates
    if _name_templates is None:
        _name_templates = {}
        try:
            for path in NAMES_DIR.glob("*.png"):
                data = np.fromfile(str(path), dtype=np.uint8)
                image = cv2.imdecode(data, cv2.IMREAD_COLOR)
                if image is not None:
                    _name_templates[path.stem] = image
        except Exception:
            pass
    return _name_templates


def name_crop(frame):
    """小地图上方两行字（地区名 + 小地图名）的固定区域。"""
    box = minimap.find_minimap(frame)
    if box is None:
        return None
    y = max(0, box.y - 42)
    crop = frame[y:box.y + 4, box.x:box.x + box.w + 40]
    return crop if crop.size else None


def match_name(crop, threshold=NAME_THRESHOLD):
    """和已存的名字截图比对；返回 (name, score)。"""
    best_name, best_score = "", 0.0
    for name, tpl in load_name_templates().items():
        if tpl.shape[:2] != crop.shape[:2]:
            tpl = cv2.resize(tpl, (crop.shape[1], crop.shape[0]))
        result = cv2.matchTemplate(crop, tpl, cv2.TM_CCOEFF_NORMED)
        score = float(result.max()) if result.size else 0.0
        if score > best_score:
            best_name, best_score = name, score
    return (best_name if best_score >= threshold else ""), best_score


def save_name_template(name, crop):
    NAMES_DIR.mkdir(parents=True, exist_ok=True)
    path = NAMES_DIR / f"{name}.png"
    if not path.exists():
        ok, buffer = cv2.imencode(".png", crop)
        if ok:
            buffer.tofile(str(path))
    load_name_templates()[name] = crop


def known_names():
    """已知小地图名：人工种子表 + 已登记的名字（不再混入大地图 OCR 的错误名）。"""
    names = set(KNOWN_EXTRA)
    try:
        saved = json.loads(NAMES_PATH.read_text(encoding="utf-8"))
        names.update(v for v in saved.values() if v)
    except Exception:
        pass
    return sorted(names)


def read_map_name(frame, box, ocr=None):
    """读小地图上方的地图名（两行：地区名 / 小地图名），返回 (地区名, 小地图名)。"""
    if box is None:
        return "", ""
    x, y = box.x, max(0, box.y - 42)
    crop = frame[y:box.y + 4, x:box.x + box.w + 40]
    if crop.size == 0:
        return "", ""
    if ocr is None:
        return "", ""
    big = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    big = cv2.copyMakeBorder(big, 14, 14, 14, 14, cv2.BORDER_REPLICATE)
    result = ocr.ocr(big)
    lines = [str(item[1][0]).strip() for item in result[0]] if result and result[0] else []
    area = lines[0] if lines else ""
    sub = lines[-1] if len(lines) > 1 else ""
    if sub:
        pool = known_names()
        if sub not in pool:
            # 只允许"补漏字"：首字相同、OCR 是候选的子序列、长度差 <= 2
            def is_subseq(a, b):
                it = iter(b)
                return all(ch in it for ch in a)
            cands = [n for n in pool
                     if n[:1] == sub[:1] and is_subseq(sub, n) and 0 <= len(n) - len(sub) <= 2]
            if len(cands) == 1:
                sub = cands[0]
    return area, sub


def fingerprint(crop, size=FINGERPRINT):
    """小地图内容的形状指纹（灰度高、图标占比小，不影响整体形状）。"""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, size, interpolation=cv2.INTER_AREA)
    bits = (small > small.mean()).astype(np.uint8)
    return bits.tobytes().hex()


@dataclass
class Observation:
    map_id: str = ""            # 地图名；认不出来就是空串（绝不放指纹）
    player: "tuple | None" = None   # 玩家位置；找不到黄点就是 None
    npcs: list = field(default_factory=list)
    portals: list = field(default_factory=list)
    dark: bool = False
    name: str = ""
    raw: str = ""               # 小地图形状指纹，仅备用
    size: tuple = (0, 0)        # 小地图内容区 (w, h)，聚类按像素半径用


def observe(frame):
    """读一帧画面 → Observation（全部坐标按小地图内容区归一化到 0~1）。"""
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    dark = float(frame.mean()) < DARK_MEAN
    box = minimap.find_minimap(frame)
    if box is None:
        return Observation(player=None, dark=dark)
    inner = box.inner()
    crop = frame[inner.y:inner.bottom, inner.x:inner.right]
    if crop.size == 0:
        return Observation(player=None, dark=dark)
    width, height = inner.w, inner.h
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

    pos = None
    candidates = player.find_candidates(frame, inner.as_tuple())
    if candidates:
        pos = ((candidates[0].x - inner.x) / width, (candidates[0].y - inner.y) / height)

    # 坐标统一用 (dx/width, dy/height)：NPC/传送门以前用 dy/width，会和玩家坐标互相污染
    npcs = [((x / width, y / height), area) for x, y, area in _blobs(hsv, *NPC_RANGE)]
    portals = [((x / width, y / height), int(score * 100)) for x, y, score in _match_portals(crop)]
    return Observation(player=pos, npcs=npcs, portals=portals, dark=dark,
                       raw=fingerprint(crop), size=(width, height))


class MapWatcher:
    """逐帧喂进去，自动记录过图。"""

    def __init__(self, visits_path=None, names_path=None, dark_mean=DARK_MEAN,
                 portals_path=None):
        self.visits_path = Path(visits_path or VISITS_PATH)
        self.seen_path = Path(portals_path or PORTALS_PATH)
        self.names_path = Path(names_path or NAMES_PATH)
        self.dark_mean = dark_mean
        self.prev = None          # 黑屏前最后一帧
        self.in_dark = False
        self.dark_started = 0.0
        self.events = []
        self._ocr = None
        self.errors = []
        self.skipped_lines = 0    # load_visits 跳过多少坏行
        self._last_map = None
        self.names_cache = self.names()
        self.portal_points = {}    # map_id -> [{"key", "x", "y", "n"}]：稳定簇
        self.map_sizes = {}        # map_id -> (w, h)：像素半径聚类用
        self.portal_icons = {}
        self.seen_portals = {}     # map_id -> {pos_key}：见过的传送门
        self.explored = set()      # (map_id, pos_key)：从这里出发过的传送门
        self._replay()             # 从落盘记录恢复进度

    def _error(self, message):
        """记录错误；只保留最近 200 条，长时间挂机也不会把内存吃光。"""
        self.errors.append(message)
        if len(self.errors) > 200:
            del self.errors[:-200]

    def _replay(self):
        """从已落盘的记录重建"见过的传送门/走过的传送门"，这样中断后能接着跑。"""
        try:
            visits = self.load_visits()
        except Exception as exc:
            self._error(f"replay: {exc}")
            visits = []
        for event in visits:
            fmap = str(event.get("from_map", "") or "")
            tmap = str(event.get("to_map", "") or "")
            if not usable_id(fmap) or not usable_id(tmap):
                continue          # 空 id / 旧占位符 / 指纹都不算真实过图
            fpos = _as_pos(event.get("from_pos"))
            tpos = _as_pos(event.get("to_pos"))
            if fpos is None or tpos is None:
                continue          # 玩家位置未知的历史事件不参与传送门统计
            fpos, tpos = pos_key(fpos), pos_key(tpos)
            if fpos == UNKNOWN_POS or tpos == UNKNOWN_POS:
                continue          # 旧版本的 (0,0) 哨兵不是真实传送门
            fpos = self.cluster(fmap, fpos)
            tpos = self.cluster(tmap, tpos)
            self.explored.add((fmap, fpos))
            self.seen_portals.setdefault(fmap, set()).add(fpos)
            self.seen_portals.setdefault(tmap, set()).add(tpos)
        for map_id, positions in self._load_portals().items():
            if not usable_id(map_id) or not isinstance(positions, list):
                continue
            bucket = self.seen_portals.setdefault(map_id, set())
            for pos in positions:
                parsed = _as_pos(pos)
                if parsed is not None and pos_key(parsed) != UNKNOWN_POS:
                    bucket.add(pos_key(parsed))
        if self.seen_portals:
            print(f"[mapwatch] 恢复进度：{len(self.seen_portals)} 张图、"
                  f"{sum(len(v) for v in self.seen_portals.values())} 个传送门、"
                  f"{len(self.explored)} 个已走过", flush=True)

    def _load_portals(self):
        """读 seen_portals.json；文件损坏就改名 .bak 并提示，不静默丢掉。"""
        if not self.seen_path.exists():
            return {}
        try:
            data = json.loads(self.seen_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("顶层不是对象")
            return data
        except Exception as exc:
            backup = self.seen_path.with_name(self.seen_path.name + ".bak")
            try:
                os.replace(self.seen_path, backup)
                print(f"[mapwatch] {self.seen_path.name} 损坏（{exc}），"
                      f"已改名 {backup.name}，重新开始", flush=True)
            except Exception as backup_exc:
                self._error(f"portals backup: {backup_exc}")
            return {}

    def _flush_portals(self):
        """临时文件 + os.replace 原子写，避免崩溃时留下半个 json。"""
        try:
            self.seen_path.parent.mkdir(parents=True, exist_ok=True)
            data = {k: sorted(list(v)) for k, v in self.seen_portals.items()
                    if usable_id(k) and v}
            temp = self.seen_path.with_name(self.seen_path.name + ".tmp")
            with temp.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.seen_path)
        except Exception as exc:
            self._error(f"flush: {exc}")

    def _radii(self, map_id):
        """这张图的聚类容差（归一化坐标）。知道小地图尺寸就按 5px 换算。"""
        size = self.map_sizes.get(map_id)
        if size and size[0] > 0 and size[1] > 0:
            return CLUSTER_PX / float(size[0]), CLUSTER_PX / float(size[1])
        return CLUSTER_RX, CLUSTER_RY     # 旧数据没有尺寸，退回归一化阈值

    def cluster(self, map_id, pos, size=None):
        """把位置吸附到这张图已有的传送门簇；返回**稳定**的 ``pos_key``。

        半径按小地图像素算（默认 5px），命中后只更新桶内质心，返回的 key
        永远不变——否则每帧的轻微抖动都会在 seen_portals 里造出一个新成员。
        """
        if pos is None:
            return None
        if size and size[0] > 0 and size[1] > 0:
            self.map_sizes[map_id] = (int(size[0]), int(size[1]))
            rx = CLUSTER_PX / float(size[0])
            ry = CLUSTER_PX / float(size[1])
        else:
            rx, ry = self._radii(map_id)
        bucket = self.portal_points.setdefault(map_id, [])
        best, best_d = None, None
        for entry in bucket:
            dx = (entry["x"] - pos[0]) / rx
            dy = (entry["y"] - pos[1]) / ry
            distance = dx * dx + dy * dy
            if distance <= 1.0 and (best_d is None or distance < best_d):
                best, best_d = entry, distance
        if best is not None:
            count = best["n"] + 1
            best["x"] = (best["x"] * best["n"] + pos[0]) / count
            best["y"] = (best["y"] * best["n"] + pos[1]) / count
            best["n"] = count
            return best["key"]
        key = pos_key(pos)
        if len(bucket) >= MAX_PORTALS:
            nearest = min(bucket, key=lambda entry: (
                ((entry["x"] - pos[0]) / rx) ** 2 + ((entry["y"] - pos[1]) / ry) ** 2))
            bucket.remove(nearest)
            self._error(f"cluster: {map_id} 传送门超过 {MAX_PORTALS} 个，丢弃最近的重复簇")
        bucket.append({"key": key, "x": pos[0], "y": pos[1], "n": 1})
        return key

    def _note_inferred_portal(self, map_id, pos):
        """过图位置不在已知图标上时提示"推断传送门"（坐标/半径和聚类保持一致）。"""
        rx, ry = self._radii(map_id)
        for icon in self.portal_icons.get(map_id, []):
            if abs(icon[0] - pos[0]) <= rx and abs(icon[1] - pos[1]) <= ry:
                return
        print(f"[mapwatch] 推断传送门：{map_id} @ ({pos[0]:.2f}, {pos[1]:.2f})", flush=True)

    def names(self):
        try:
            return json.loads(self.names_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def name_of(self, map_id):
        # 现在 map_id 本身就是名字；旧缓存只作兼容
        return self.names_cache.get(map_id) or map_id

    def _ocr_instance(self):
        if self._ocr is None:
            import logging

            from paddleocr import PaddleOCR

            logging.getLogger("ppocr").setLevel(logging.ERROR)
            self._ocr = PaddleOCR(lang="ch", show_log=False)
            from .vision import silence_ocr_logs
            silence_ocr_logs()
        return self._ocr

    def _correct_name(self, sub):
        """把 OCR 结果纠到已知地图名：先换字（同长度/同尾号/相似），再近似匹配。"""
        pool = list(KNOWN_EXTRA)
        for name in load_name_templates():
            if name not in pool:
                pool.append(name)
        if not sub or not pool:
            return sub
        tail = re.search(r"(\d+)$", sub)
        tail_digits = tail.group(1) if tail else ""
        cands = []
        for cand in pool:
            if len(cand) != len(sub):
                continue
            cand_tail = re.search(r"(\d+)$", cand)
            if (cand_tail.group(1) if cand_tail else "") == tail_digits:
                cands.append(cand)
        best = max(cands, key=lambda c: difflib.SequenceMatcher(None, sub, c).ratio(),
                   default=None)
        if best and difflib.SequenceMatcher(None, sub, best).ratio() >= 0.55:
            return best
        close = difflib.get_close_matches(sub, pool, n=1, cutoff=0.70)
        return close[0] if close else sub

    def _resolve_name(self, frame, obs):
        """给 obs 定名字：模板匹配优先，其次 OCR + 纠错；失败留空。

        这是唯一的命名入口——``map_id`` 在这里只会变成真实名字或空串，
        不存在"指纹当 id"或"未知地图当 id"的路径。
        """
        name = ""
        crop = None
        try:
            crop = name_crop(frame)
        except Exception as exc:
            self._error(f"crop: {exc}")
        if crop is not None:
            try:
                name, _score = match_name(crop)
            except Exception as exc:
                self._error(f"match_name: {exc}")
                name = ""
            if not name:
                sub = ""
                try:
                    box = minimap.find_minimap(frame)
                    _area, sub = read_map_name(frame, box, self._ocr_instance())
                except Exception as exc:
                    self._error(f"ocr: {exc}")
                if sub:
                    name = self._correct_name(sub)
                    try:
                        # 即使名字来自白名单也存模板，下一帧就能直接匹配
                        save_name_template(name, crop)
                        print(f"[mapwatch] 新地图名入库：{name}", flush=True)
                    except Exception as exc:
                        self._error(f"save_template: {exc}")
        if name and not usable_id(name):
            name = ""
        obs.name = name
        obs.map_id = name
        return name

    def step(self, frame, now=None):
        """处理一帧；发生过图就返回一条事件，否则 None。"""
        now = time.monotonic() if now is None else now
        try:
            obs = observe(frame)
        except Exception as exc:
            self._error(f"observe: {exc}")
            return None
        if obs is None:
            return None

        if obs.dark:
            obs.map_id = ""
            if not self.in_dark:
                self.in_dark = True
                self.dark_started = now
            return None

        # 统一命名：模板 -> OCR + 纠错；失败就是空串，绝不用指纹/占位符顶替
        try:
            self._resolve_name(frame, obs)
        except Exception as exc:
            self._error(f"name: {exc}")
            obs.name = ""
            obs.map_id = ""

        if self.in_dark:
            self.in_dark = False
            load_ms = (now - self.dark_started) * 1000.0
            before, self.prev = self.prev, obs
            # 两边都必须是真实地图名；否则不写事件（prev 已更新，不会卡住）
            if before is None or not usable_id(before.map_id) or not usable_id(obs.map_id):
                return None
            if before.map_id == obs.map_id:
                return None           # 黑屏但没换图（过场/切场景），忽略
            if before.player is None or obs.player is None:
                # 位置未知时宁可不记，也不把 (0,0) 当真实传送门写进图
                print(f"[mapwatch] 玩家位置未知，跳过 {before.map_id} -> {obs.map_id}", flush=True)
                return None
            from_pos = self.cluster(before.map_id, before.player, before.size)
            to_pos = self.cluster(obs.map_id, obs.player, obs.size)
            self._note_inferred_portal(before.map_id, from_pos)
            self.explored.add((before.map_id, from_pos))
            self.seen_portals.setdefault(before.map_id, set()).add(from_pos)
            self.seen_portals.setdefault(obs.map_id, set()).add(to_pos)
            event = {
                "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "from_map": before.map_id, "from_pos": list(from_pos),
                "to_map": obs.map_id, "to_pos": list(to_pos),
                "load_ms": round(load_ms, 0),
                "from_name": self.name_of(before.map_id), "to_name": self.name_of(obs.map_id),
            }
            self._append(event)
            self._flush_portals()
            self.events.append(event)
            return event

        # 顺带记录这张图上看到的传送门（数量 1~4 才可信，防误检）
        if obs.map_id and 1 <= len(obs.portals) <= 4:
            # 只记录、不计入"未跑传送门"：图标匹配会有误检，计数以过图为准
            self.portal_icons[obs.map_id] = [self.cluster(obs.map_id, pos, obs.size)
                                             for pos, _area in obs.portals]
        # 第一次看到某张图 / 开图时，明确告诉用户"我现在在哪"
        if obs.map_id and obs.map_id != self._last_map:
            self._last_map = obs.map_id
            print(f"[mapwatch] 当前地图：{obs.map_id}", flush=True)

        # 没有黑屏但地图变了（少数过图不黑屏），也记一条
        previous = self.prev
        if (previous is not None and usable_id(previous.map_id) and usable_id(obs.map_id)
                and previous.map_id != obs.map_id):
            if previous.player is None or obs.player is None:
                print(f"[mapwatch] 玩家位置未知，跳过 {previous.map_id} -> {obs.map_id}",
                      flush=True)
                self.prev = obs
                return None
            from_pos = self.cluster(previous.map_id, previous.player, previous.size)
            to_pos = self.cluster(obs.map_id, obs.player, obs.size)
            self._note_inferred_portal(previous.map_id, from_pos)
            self.explored.add((previous.map_id, from_pos))
            self.seen_portals.setdefault(previous.map_id, set()).add(from_pos)
            self.seen_portals.setdefault(obs.map_id, set()).add(to_pos)
            event = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                     "from_map": previous.map_id, "from_pos": list(from_pos),
                     "to_map": obs.map_id, "to_pos": list(to_pos),
                     "load_ms": None, "no_black": True,
                     "from_name": self.name_of(previous.map_id),
                     "to_name": self.name_of(obs.map_id)}
            self._append(event)
            self._flush_portals()
            self.events.append(event)
            self.prev = obs
            return event

        self.prev = obs
        return None

    def _append(self, event):
        """追加一条 jsonl；写完立刻 flush，进程崩了也不丢已记的过图。"""
        self.visits_path.parent.mkdir(parents=True, exist_ok=True)
        with self.visits_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            handle.flush()

    # ------------------------------------------------------------ 报告
    def load_visits(self):
        """逐行读 jsonl：坏行跳过并计数，不影响其余记录。"""
        try:
            text = self.visits_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self.skipped_lines = 0
            return []
        except Exception as exc:
            self._error(f"load_visits: {exc}")
            self.skipped_lines = 0
            return []
        visits = []
        bad = 0
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                bad += 1
                continue
            if not isinstance(event, dict):
                bad += 1
                continue
            visits.append(event)
        self.skipped_lines = bad
        if bad:
            self._error(f"load_visits: 跳过 {bad} 行损坏记录")
        return visits

    def report(self):
        visits = self.load_visits()
        maps = {}
        edges = {}
        valid = 0
        for event in visits:
            fmap = str(event.get("from_map", "") or "")
            tmap = str(event.get("to_map", "") or "")
            # 空 id / 旧占位符 / 指纹都不进报告
            if not usable_id(fmap) or not usable_id(tmap):
                continue
            valid += 1
            maps[fmap] = maps.get(fmap, 0) + 1
            maps[tmap] = maps.get(tmap, 0) + 1
            edges[(fmap, tmap)] = edges.get((fmap, tmap), 0) + 1
        names = self.names()
        unexplored = []
        for map_id, portals in self.seen_portals.items():
            if not usable_id(map_id):
                continue
            for pos in sorted(portals):
                if pos_key(pos) == UNKNOWN_POS:
                    continue      # 旧版本哨兵坐标，不能当成"未跑传送门"
                if (map_id, pos_key(pos)) not in self.explored:
                    unexplored.append({"map": map_id, "name": names.get(map_id) or map_id,
                                       "pos": [round(v, 3) for v in pos]})
        return {
            "visits": valid,
            "unexplored": unexplored,
            "maps": [{"id": mid, "name": names.get(mid) or mid, "count": count}
                     for mid, count in sorted(maps.items(), key=lambda kv: -kv[1])],
            "edges": [{"from": a, "to": b, "count": c}
                      for (a, b), c in sorted(edges.items(), key=lambda kv: -kv[1])],
        }


# ---------------------------------------------------------------- 运行
class _Tee:
    """把控制台输出同时写进日志文件（补齐第三方库会用的文件接口）。"""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            try:
                stream.write(data)
                stream.flush()
            except Exception:
                pass
        return len(data)

    def flush(self):
        for stream in self.streams:
            try:
                stream.flush()
            except Exception:
                pass

    @property
    def encoding(self):
        for stream in self.streams:
            encoding = getattr(stream, "encoding", None)
            if encoding:
                return encoding
        return "utf-8"

    @property
    def errors(self):
        for stream in self.streams:
            errors = getattr(stream, "errors", None)
            if errors:
                return errors
        return "replace"

    def fileno(self):
        for stream in self.streams:
            fileno = getattr(stream, "fileno", None)
            if fileno is None:
                continue
            try:
                return fileno()
            except Exception:
                continue
        raise OSError("_Tee 没有可用的 fileno")

    def isatty(self):
        for stream in self.streams:
            try:
                if stream.isatty():
                    return True
            except Exception:
                continue
        return False


def _grabber():
    import mss
    import win32gui

    best = None

    def callback(hwnd, _):
        nonlocal best
        if not win32gui.IsWindowVisible(hwnd) or win32gui.GetWindowText(hwnd) != "MapleStory":
            return
        rect = win32gui.GetWindowRect(hwnd)
        area = (rect[2] - rect[0]) * (rect[3] - rect[1])
        if best is None or area > best[0]:
            best = (area, hwnd)

    win32gui.EnumWindows(callback, None)
    if best is None:
        raise SystemExit("找不到 MapleStory 窗口")
    hwnd = best[1]
    ox, oy = win32gui.ClientToScreen(hwnd, (0, 0))
    cw, ch = win32gui.GetClientRect(hwnd)[2:]

    def grab():
        with mss.mss() as sct:
            shot = sct.grab({"left": ox, "top": oy, "width": cw, "height": ch})
            return np.array(shot)[:, :, :3].copy()

    return grab


def _main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="跑商地图信息收集")
    parser.add_argument("--run", action="store_true", help="接游戏实时收集")
    parser.add_argument("--report", action="store_true", help="输出已收集的地图/连接")
    parser.add_argument("--interval", type=float, default=0.1)
    parser.add_argument("--log", default=str(ROOT / "detections" / "mapwatch.log"), help="日志文件")
    args = parser.parse_args(argv)

    if args.log:
        log_path = Path(args.log)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = log_path.open("a", encoding="utf-8")
        handle.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动 =====\n")
        handle.flush()
        sys.stdout = _Tee(sys.__stdout__, handle)
        sys.stderr = _Tee(sys.__stderr__, handle)
        print(f"[mapwatch] 日志写入 {log_path}", flush=True)

    watcher = MapWatcher()
    if args.run:
        grab = _grabber()
        print("开始收集，Ctrl+C 结束")
        failures = 0
        try:
            while True:
                delay = args.interval
                try:
                    event = watcher.step(grab())
                    if event:
                        data = watcher.report()
                        left = data["unexplored"]
                        ms = event.get("load_ms")
                        timing = f"{ms:.0f} ms" if isinstance(ms, (int, float)) else "无黑屏"
                        print(f"过图 {event['from_map']} -> {event['to_map']} "
                              f"({timing}) | 地图 {len(data['maps'])} 张 "
                              f"连接 {len(data['edges'])} 条 | 未跑传送门 {len(left)} 个", flush=True)
                        for item in left[:3]:
                            print(f"    未跑: {item['map'][:8]} @ {item['pos']}", flush=True)
                    failures = 0
                except Exception as exc:
                    # 单帧/单次识别出错不退出，退避后继续；长时间挂机必需
                    failures += 1
                    watcher._error(f"run: {exc}")
                    print(f"[mapwatch] 采集异常（连续第 {failures} 次），1 秒后继续："
                          f"{exc}", flush=True)
                    delay = 1.0
                time.sleep(max(0.0, delay))
        except KeyboardInterrupt:
            print("停止")
    if args.report or not args.run:
        data = watcher.report()
        print(json.dumps({"visits": data["visits"],
                          "maps": len(data["maps"]), "edges": len(data["edges"]),
                          "unexplored": len(data["unexplored"])},
                         ensure_ascii=False))
        for item in data["maps"][:10]:
            print("  map", item)
        for item in data["edges"][:10]:
            print("  edge", item)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
