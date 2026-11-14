"""跑商地图信息收集：小地图指纹 + 过图记录 + 传送门配对。

设计：
- **地图身份**用地图名：先和已存名字截图做模板匹配，再 OCR + 补字/换字纠错；
  形状指纹只放在 ``Observation.raw`` 里备用，**绝不**当 ``map_id``；
- **过图**判定只有一条：前后两次"有名字"的观测地图名不一样，就是一次过图；
  黑屏只用来量 ``load_ms``（以及卡加载告警），**不参与**"是否过图"的判断；
- **出发传送门** = 换图前最后一次有名字的观测里的玩家位置（过图必须在传送门上）；
- **到达传送门** = 换图后第一帧有名字的观测里的玩家位置（角色正站在传送门上，图标被挡住也能定位）；
- 坐标全部按小地图内容区归一化到 0~1；
- **影响地图记录的异常立刻报警**：以 ``！！！！！`` 开头打印，同一原因首次 +
  每 60 秒一次，提醒玩家停下来别继续白跑。

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
NAME_THRESHOLD = 0.92
NAME_MARGIN = 0.08
NAME_SIZE = (240, 44)
_CROP_NAMES = {}   # 裁剪像素哈希 -> 名字：同一画面不重复问视觉   # 固定裁剪尺寸：锚定小地图左上角，不随面板宽度变化
NAMES_PATH = ROOT / "data" / "trade" / "map_names.json"

#: 小地图图标颜色（实测：NPC 蓝点 H 85~110，传送门绿圈 H 40~80）
NPC_RANGE = ((85, 120, 120), (110, 255, 255))
PORTAL_TEMPLATE = ROOT / "data" / "trade" / "icons" / "portal.png"
PORTAL_THRESHOLD = 0.80
#: 全屏变黑判定：平均亮度低于这个值算 loading
DARK_MEAN = 40
#: 影响地图记录的异常一律以此为前缀，方便一眼发现 / grep
ALARM_PREFIX = "！！！！！"
#: 连续读不出地图名多久后报警（小地图还在，但名字是空的）
BLANK_ALARM_SEC = 3.0
#: 连续找不到小地图多久后报警（被窗口遮挡 / 不在跑商地图）
NO_MINIMAP_ALARM_SEC = 3.0
#: 黑屏持续多久算"可能卡在加载"
DARK_ALARM_SEC = 30.0
#: 同一条报警最短重复间隔；首次一定打印
ALARM_REPEAT_SEC = 60.0
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
    """小地图上方的名字区域：**固定尺寸**，锚定面板左上角。

    不能用 box.w 决定宽度——小地图面板宽度每张图都不一样（165/192/223 都见过），
    裁剪尺寸一变，模板就得拉伸，字被拉变形后就会认成隔壁地图。
    """
    box = minimap.find_minimap(frame)
    if box is None:
        return None
    # 跑商界面里小地图固定左上角；跑偏时会把窗口标题栏当成地图名
    if box.y < 60 or box.x > 400:
        return None
    width, height = NAME_SIZE
    x = max(0, box.x)
    y = max(0, box.y - 42)
    crop = frame[y:y + height, x:x + width]
    if crop.shape[0] != height or crop.shape[1] != width:
        return None          # 贴边/越界：宁可不认，也不能拿残缺图去比
    return crop


def name_mask(crop):
    """名字区域二值化成墨迹蒙版：半透明背景被阈值吃掉，只留文字。"""
    if crop is None or crop.size == 0:
        return None
    text = crop[:, 40:] if crop.shape[1] > 60 else crop
    gray = cv2.cvtColor(text, cv2.COLOR_BGR2GRAY)
    return (gray >= max(180, int(np.median(gray)) + 100)).astype(np.uint8)


def mask_iou(a, b):
    if a is None or b is None or a.shape != b.shape:
        return 0.0
    inter = int(np.logical_and(a, b).sum())
    union = int(np.logical_or(a, b).sum())
    return inter / union if union else 0.0


def match_name(crop, threshold=NAME_THRESHOLD, margin=NAME_MARGIN):
    """和名字模板比对，返回 (name, best, second)。

    尺寸不同直接跳过（绝不拉伸）；还要求第一名领先第二名 margin，
    这样 "沙漠-1/2/3" 这种只差一个数字的名字不会互相误认。
    """
    scores = []
    for name, tpl in load_name_templates().items():
        if tpl.shape[:2] != crop.shape[:2]:
            continue
        result = cv2.matchTemplate(crop, tpl, cv2.TM_CCOEFF_NORMED)
        if not result.size:
            continue
        # 只差一个数字的名字（-1 vs -2）NCC 仍有 0.994，必须再比墨迹蒙版
        if mask_iou(name_mask(crop), name_mask(tpl)) < 0.95:
            continue
        scores.append((float(result.max()), name))
    if not scores:
        return "", 0.0, 0.0
    scores.sort(reverse=True)
    best, best_name = scores[0]
    second = scores[1][0] if len(scores) > 1 else 0.0
    if best >= threshold and best - second >= margin:
        return best_name, best, second
    return "", best, second


def save_name_template(name, crop):
    """保存模板；返回 True 表示是新建（用于只在首次打印）。"""
    if crop is None or crop.shape[:2] != (NAME_SIZE[1], NAME_SIZE[0]):
        return False
    NAMES_DIR.mkdir(parents=True, exist_ok=True)
    path = NAMES_DIR / f"{name}.png"
    created = False
    if not path.exists():
        ok, buffer = cv2.imencode(".png", crop)
        if ok:
            buffer.tofile(str(path))
            created = True
    load_name_templates()[name] = crop
    return created


def plausible_name(name):
    """名字必须是白名单里的，或 3~10 个汉字且不含 UI 词。"""
    if not name or len(name) > 12:
        return False
    if name in KNOWN_EXTRA:
        return True
    if any(word in name for word in UI_WORDS):
        return False
    if sum(1 for ch in name if "\u4e00" <= ch <= "\u9fff") < 2:
        return False       # "MapleStory" 这种拒掉
    cjk = sum(1 for ch in name if "\u4e00" <= ch <= "\u9fff")
    return cjk >= 4


def known_names():
    """已知小地图名：人工种子表 + 已登记的名字（不再混入大地图 OCR 的错误名）。"""
    names = set(KNOWN_EXTRA)
    try:
        saved = json.loads(NAMES_PATH.read_text(encoding="utf-8"))
        names.update(v for v in saved.values() if v)
    except Exception:
        pass
    return sorted(names)


VISION_SYSTEM = "你是冒险岛地图名识别器。图片是小地图上方的文字，第一行是地区名，第二行是小地图名。只输出第二行的地图名原文，不要引号、不要标点、不要解释。"


def _vision_read(crop):
    """用 DeepSeek 视觉读小地图名（比 12px 繁体 OCR 可靠），返回第二行文字。"""
    from .vision import VisionClient

    text = VisionClient().ask(crop, system=VISION_SYSTEM,
                        user="只输出第二行（小地图名）。", max_tokens=32)
    if not text:
        return ""
    line = [ln.strip() for ln in str(text).splitlines() if ln.strip()]
    if not line:
        return ""
    name = line[-1].strip(' \"\'。）)』」【】[]')
    return name


def read_map_name(frame, box, ocr=None):
    """读小地图上方的地图名，返回 (地区名, 小地图名)。

    `ocr` 传 None 时走 DeepSeek 视觉（默认路径）；传了 OCR 引擎则走旧 OCR 路径
    （测试和离线场景用）。
    """
    if box is None:
        return "", ""
    crop = name_crop(frame)
    if crop is None or crop.size == 0:
        return "", ""
    if ocr is None:
        try:
            return "", _vision_read(crop)
        except Exception:
            return "", ""
    big = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    big = cv2.copyMakeBorder(big, 14, 14, 14, 14, cv2.BORDER_REPLICATE)
    result = ocr.ocr(big)
    lines = [str(item[1][0]).strip() for item in result[0]] if result and result[0] else []
    area = lines[0] if lines else ""
    sub = lines[-1] if len(lines) > 1 else ""
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
        #: 上一次"有名字"的观测——判过图只认它，空名字帧顶不掉它
        self.last_map_obs = None
        self.in_dark = False
        self.dark_started = 0.0
        #: 最近一次黑屏的时长（ms），留给下一次换图结算；黑屏没换图就作废
        self._pending_load_ms = None
        self.events = []
        self.alarms = []          # 本次运行打印过的告警（已按原因去重）
        self.alarm_count = 0
        self._alarm_last = {}
        self._none_since = None
        self._startup_named = False
        self._started_at = None     # 告警 code -> 上次打印时间
        self._blank_since = None  # 连续读不出名字的起点
        self._no_map_since = None # 连续找不到小地图的起点
        self._missed_from = False # 进黑屏前就没记住地图名 → 出发侧未知
        self._ocr = None
        self.errors = []
        self.skipped_lines = 0    # load_visits 跳过多少坏行
        self._last_map = None
        self.names_cache = self.names()
        self.portal_points = {}    # map_id -> [{"key", "x", "y", "n"}]：稳定簇
        self.map_sizes = {}        # map_id -> (w, h)：像素半径聚类用
        self.portal_icons = {}
        self.seen_portals = {}     # map_id -> {pos_key}：见过的传送门
        self.explored = set()      # (map_id, pos_key)：确认过的传送门（出发或到达）
        self._replay()             # 从落盘记录恢复进度

    def _error(self, message):
        """记录错误；只保留最近 200 条，长时间挂机也不会把内存吃光。"""
        self.errors.append(message)
        if len(self.errors) > 200:
            del self.errors[:-200]

    def _alarm(self, code, reason, now=None):
        """打印一条"地图记录异常"告警。

        同一 ``code`` 只在首次和之后每 ``ALARM_REPEAT_SEC`` 秒各打一次，
        避免每帧刷屏；不同原因各自独立计时。"立刻"指当帧就打印并 flush。
        返回这次是否真的打印了。
        """
        now = time.monotonic() if now is None else now
        last = self._alarm_last.get(code)
        if last is not None and 0 <= (now - last) < ALARM_REPEAT_SEC:
            return False
        self._alarm_last[code] = now
        self.alarm_count += 1
        self.alarms.append({"t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "code": code, "reason": reason})
        if len(self.alarms) > 200:
            del self.alarms[:-200]
        print(f"{ALARM_PREFIX} 地图记录异常：{reason}，请暂停跑图并通知开发者",
              flush=True)
        return True

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
            self.explored.add((tmap, tpos))   # 到达过也算已知
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

    def _flush_portals(self, now=None):
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
            return True
        except Exception as exc:
            self._error(f"flush: {exc}")
            self._alarm("write_portals",
                        f"写 {self.seen_path.name} 失败：{exc}（传送门记录没有落盘）",
                        now)
            return False

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

    def _resolve_name(self, frame, obs, now=None):
        """给 obs 定名字：模板匹配优先，其次 OCR + 纠错；失败留空。

        这是唯一的命名入口——``map_id`` 在这里只会变成真实名字或空串，
        不存在"指纹当 id"或"未知地图当 id"的路径。解析链路抛异常会立刻
        报警（需求 7），同时这一帧按"没名字"处理。
        """
        name = ""
        crop = None
        try:
            crop = name_crop(frame)
        except Exception as exc:
            self._error(f"crop: {exc}")
            self._alarm("name_crop", f"截取地图名区域抛异常：{exc}", now)
        if crop is not None:
            import hashlib as _hashlib
            _crop_key = _hashlib.md5(crop.tobytes()).hexdigest()
            name = _CROP_NAMES.get(_crop_key, "")
            _score = 1.0 if name else 0.0
            try:
                if not name:
                    name, _score = match_name(crop)
            except Exception as exc:
                self._error(f"match_name: {exc}")
                self._alarm("name_match", f"地图名模板匹配抛异常：{exc}", now)
                name = ""
            if not name:
                sub = ""
                box = None
                try:
                    box = minimap.find_minimap(frame)
                except Exception as exc:
                    # 小地图都定位不了：这一帧算"没名字"，由 3 秒告警兜底
                    self._error(f"find_minimap: {exc}")
                try:
                    _area, sub = read_map_name(frame, box)
                except Exception as exc:
                    self._error(f"ocr: {exc}")
                    self._alarm("name_ocr", f"地图名 OCR 抛异常：{exc}", now)
                if sub:
                    name = self._correct_name(sub)
                    if name:
                        _CROP_NAMES[_crop_key] = name
                    if name not in KNOWN_EXTRA:
                        # 不在跑商地图白名单：说明已离开跑商（回城/活动结束），
                        # 不能当成新地图记进图
                        print(f"[mapwatch] 已离开跑商地图（读到：{name}），暂停记录", flush=True)
                        self._alarm("left_trade", f"读到非跑商地图名：{name}，已暂停记录", now)
                        name = ""
                    try:
                        # 即使名字来自白名单也存模板，下一帧就能直接匹配
                        if save_name_template(name, crop):
                            print(f"[mapwatch] 新地图名入库：{name}", flush=True)
                    except Exception as exc:
                        self._error(f"save_template: {exc}")
        if name and not usable_id(name):
            name = ""
        obs.name = name
        obs.map_id = name
        if name and not plausible_name(name):
            self._error(f"地图名不合理，丢弃：{name!r}")
            obs.name = ""
            obs.map_id = ""
            return ""
        return name

    def step(self, frame, now=None):
        """处理一帧；地图名发生变化就返回一条过图事件，否则 None。

        判定只有一条：**前后两次"有名字"的观测地图名不一样 = 一次过图**。
        黑屏只用来量 ``load_ms`` / 报"卡加载"，不再决定有没有过图。
        """
        now = time.monotonic() if now is None else now
        try:
            obs = observe(frame)
        except Exception as exc:
            self._error(f"observe: {exc}")
            self._alarm("observe", f"observe() 抛异常：{exc}", now)
            return None
        if obs is None:
            if self._none_since is None:
                self._none_since = now
            elif now - self._none_since >= 2.0:
                self._alarm("no_frame", "连续 2 秒拿不到画面（最小化/被挡/不在游戏）", now)
            return None
        self._none_since = None

        # ---- 黑屏：只计时，不解析名字（黑屏上没有名字可读）
        if obs.dark:
            if not self.in_dark:
                self.in_dark = True
                self.dark_started = now
                self._pending_load_ms = None
                self._blank_since = None        # 黑屏时间不算"读不出名字"
                self._no_map_since = None
                if self.last_map_obs is None:
                    # 进黑屏前就不知道在哪张图：这次过图的出发侧注定丢了
                    self._missed_from = True
            dark_sec = now - self.dark_started
            if dark_sec >= DARK_ALARM_SEC:
                self._alarm("dark", f"黑屏已持续 {dark_sec:.1f} 秒（可能卡在加载）", now)
            return None

        # ---- 黑屏结束：先记下这次 loading 时长，等下一次"真的换图"结算
        if self.in_dark:
            self.in_dark = False
            self._pending_load_ms = max(0.0, (now - self.dark_started) * 1000.0)
            self.dark_started = 0.0

        # ---- 统一命名：模板 -> OCR + 纠错；失败就是空串，绝不用指纹/占位符顶替
        try:
            self._resolve_name(frame, obs, now)
        except Exception as exc:
            self._error(f"name: {exc}")
            obs.name = ""
            obs.map_id = ""
            self._alarm("name", f"名字解析抛异常：{exc}", now)

        named = usable_id(obs.map_id)
        self._track_visibility(obs, named, now)

        # ---- 唯一的过图判定：两次"有名字"的观测之间地图名变了
        event = None
        last = self.last_map_obs
        if named:
            if last is not None and last.map_id != obs.map_id:
                event = self._record_transition(last, obs, self._pending_load_ms, now)
                self._pending_load_ms = None
            elif last is None and self._missed_from:
                # 黑屏前没记住地图名：知道换了图，但接不上出发侧，等于丢一条边
                self._alarm("lost_from",
                            "过图时出发侧地图名不可用，已丢失一条地图连接", now)
                self._pending_load_ms = None
            elif last is not None:
                self._pending_load_ms = None    # 黑屏了但没换图，这次时长作废
            self._missed_from = False
            if not self._startup_named:
                self._startup_named = True
                print(f"[mapwatch] 起点地图：{obs.map_id}", flush=True)
            self._remember(obs)

        # ---- 顺带记录这张图上看到的传送门（数量 1~4 才可信，防误检）
        if named and 1 <= len(obs.portals) <= 4:
            # 只记录、不计入"未跑传送门"：图标匹配会有误检，计数以过图为准
            self.portal_icons[obs.map_id] = [self.cluster(obs.map_id, pos, obs.size)
                                             for pos, _area in obs.portals]

        # ---- 第一次看到某张图 / 开图时，明确告诉用户"我现在在哪"
        if named and obs.map_id != self._last_map:
            self._last_map = obs.map_id
            print(f"[mapwatch] 当前地图：{obs.map_id}", flush=True)
        return event

    def _track_visibility(self, obs, named, now):
        """连续读不出名字 / 连续找不到小地图 → 立刻报警（需 3 秒，已去重）。"""
        has_minimap = bool(obs.size and obs.size[0] > 0 and obs.size[1] > 0)
        if not has_minimap:
            self._blank_since = None
            if self._no_map_since is None:
                self._no_map_since = now
            elif now - self._no_map_since >= NO_MINIMAP_ALARM_SEC:
                self._alarm("no_minimap",
                            f"已连续 {now - self._no_map_since:.1f} 秒找不到小地图"
                            "（被窗口遮挡或不在跑商地图）", now)
            return
        self._no_map_since = None
        if named:
            self._blank_since = None
            return
        if self._blank_since is None:
            self._blank_since = now
        elif now - self._blank_since >= BLANK_ALARM_SEC:
            self._alarm("blank_name",
                        f"已连续 {now - self._blank_since:.1f} 秒解析不出地图名", now)

    def _record_transition(self, before, obs, load_ms, now):
        """把一次真实的换图写成事件；出发/到达位置各自"能测就测"。"""
        if not usable_id(before.map_id):
            # last_map_obs 只会存有名字的帧；这里兜底，绝不写半条边
            self._alarm("lost_from",
                        "过图时出发侧地图名不可用，已丢失一条地图连接", now)
            return None
        from_pos = to_pos = None
        if before.player is not None:
            from_pos = self.cluster(before.map_id, before.player, before.size)
            self._note_inferred_portal(before.map_id, from_pos)
            self.explored.add((before.map_id, from_pos))
            self.seen_portals.setdefault(before.map_id, set()).add(from_pos)
        if obs.player is not None:
            to_pos = self.cluster(obs.map_id, obs.player, obs.size)
            self.seen_portals.setdefault(obs.map_id, set()).add(to_pos)
            self.explored.add((obs.map_id, to_pos))
        if from_pos is None or to_pos is None:
            lost = [label for label, value in (("出发位置", from_pos), ("到达位置", to_pos))
                    if value is None]
            # 角色刚过图时正站在传送门上，黄点被挡是常态，不是故障。
            # 只降级提示：边照记，坐标等绿圈露出来再补。不占用 ！！！！！ 告警。
            print(f"[mapwatch] ⚠️ 换图 {before.map_id} -> {obs.map_id} 时"
                  f"{'/'.join(lost)}暂时不可用，已降级记录（角色挡住传送门属正常）", flush=True)
        event = {
            "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "from_map": before.map_id,
            "from_pos": list(from_pos) if from_pos is not None else None,
            "to_map": obs.map_id,
            "to_pos": list(to_pos) if to_pos is not None else None,
            "load_ms": round(load_ms, 0) if load_ms is not None else None,
            "from_name": self.name_of(before.map_id),
            "to_name": self.name_of(obs.map_id),
        }
        self._append(event, now)
        self._flush_portals(now)
        self.events.append(event)
        return event

    def _remember(self, obs):
        """只记住"有名字"的帧：过图瞬间名字可能读不出来，不能让它把上一张好图冲掉。"""
        if usable_id(obs.map_id):
            self.last_map_obs = obs

    def _append(self, event, now=None):
        """追加一条 jsonl；写完立刻 flush，进程崩了也不丢已记的过图。

        写失败（磁盘满/权限）只报警、不往上抛：一帧写不进去不能让采集循环崩掉。
        """
        try:
            self.visits_path.parent.mkdir(parents=True, exist_ok=True)
            with self.visits_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
                handle.flush()
            return True
        except Exception as exc:
            self._error(f"append: {exc}")
            self._alarm("write_visits",
                        f"写 {self.visits_path.name} 失败：{exc}（这次过图没有落盘）",
                        now)
            return False

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
        print(f"本次运行：过图 {len(watcher.events)} 次，告警 {watcher.alarm_count} 次",
              flush=True)
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
