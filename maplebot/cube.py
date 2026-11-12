"""洗魔方（附加潜能）界面识别与判定。

只关心「附加潛在能力」的三行属性。位置固定：Y 固定，X 随文字长度变。

每行的结构：

    [L/U 徽章]  属性 +数值[%]      或      每9級 属性 +2

等级徽章颜色（实测）：
    L（传说）BGR (0,255,204) → HSV H=36
    U（独特）BGR (0,204,255) → HSV H=24
两者都是 S=255/V=255 的纯色块，取中心一个像素就能判。

数值规则（装备等级 250 vs 更低）：
    单属性 %：250 级 L=9 / U=7；更低 L=8 / U=6
    全屬性 %：250 级 L=7 / U=6；更低 L=6 / U=5
    每9級 +x：x ∈ {1,2}，只关心 +2
依据是**数值反推**装备档位，不需要读装备等级。
"""

import difflib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

ASSETS_DIR = Path(__file__).resolve().parents[1] / "haikuScripts" / "assets"

#: 三行属性在游戏窗口内的位置（比例，基于 1382×807 实测）
BADGE_X = 0.1896          # 徽章左边缘
BADGE_W = 0.0116         # 徽章宽度
TEXT_X0 = 0.204          # 属性文字起点
TEXT_X1 = 0.420          # 属性文字右边界
ROW_Y = (0.452, 0.478, 0.506)   # 三行文字的中心
ROW_H = 0.022            # 单行高度

#: 等级徽章的色相（OpenCV H，0~179）
GRADE_L_HUE = 36
GRADE_U_HUE = 24
BADGE_S_MIN = 200
BADGE_V_MIN = 180

#: 允许的数值
PCT_SINGLE = {6, 7, 8, 9}     # 单属性百分比
PCT_ALL = {5, 6, 7, 8}        # 全屬性百分比
PER_LEVEL_VALUE = 2           # 每9級 +2 才有用

MAIN_STATS = ("STR", "DEX", "INT", "LUK")

_RE_PCT = re.compile(r"(STR|DEX|INT|LUK|全[屬属]?[性]?)\s*[+＋]\s*(\d+)\s*%")
_RE_FLAT = re.compile(r"(STR|DEX|INT|LUK|全[屬属]?[性]?)\s*[+＋]\s*(\d+)\s*$")
_RE_PER_LEVEL = re.compile(r"每\s*9\s*[級级]\s*(?:為準|为准)?\s*([A-Za-z]{1,3})\s*[+＋]\s*(\d+)")

#: OCR 常把 DEX 認成 DE、LUK 認成 LU，這裡做前綴補全
_STAT_ALIASES = {
    "STR": "STR", "ST": "STR", "S": "STR",
    "DEX": "DEX", "DE": "DEX", "DX": "DEX", "D": "DEX",
    "INT": "INT", "IN": "INT", "I": "INT",
    "LUK": "LUK", "LU": "LUK", "LK": "LUK", "L": "LUK",
}


def normalize_stat(name):
    """把 OCR 出来的属性名补全成 STR/DEX/INT/LUK/ALL（认不出返回原样）。

    先查别名表，再按相似度就近匹配（OCR 常见 DEK/ETR 这种错一个字母的情况）。
    """
    key = (name or "").upper().strip()
    if key in _STAT_ALIASES:
        return _STAT_ALIASES[key]
    if key.startswith("全"):
        return "ALL"
    best, score = key, 0.0
    for stat in MAIN_STATS:
        ratio = difflib.SequenceMatcher(None, key, stat).ratio()
        if ratio > score:
            best, score = stat, ratio
    return best if score >= 0.6 else key
#: 兜底：其它属性行（MaxHP、攻擊力…）也要认出来，只是判定为"没用"
_RE_ANY = re.compile(r"([A-Za-z][A-Za-z ]*|[\u4e00-\u9fff]+)\s*[+＋]\s*(\d+)\s*(%?)")

_FULLWIDTH = {ord(c): str(i) for i, c in enumerate("０１２３４５６７８９")}
_FULLWIDTH.update({ord("＋"): "+", ord("％"): "%", ord("　"): " "})


def _normalize(text):
    return (text or "").translate(_FULLWIDTH).strip()


@dataclass(frozen=True)
class PotentialLine:
    """一条附加潜能。"""

    raw: str
    grade: str          # "L" / "U" / "?"
    stat: str = ""      # STR/DEX/INT/LUK/ALL
    kind: str = ""      # "pct" / "flat" / "perlevel"
    value: int = 0

    @property
    def ok(self):
        return bool(self.stat) and self.kind in ("pct", "flat", "perlevel")


def parse_line(text):
    """把一行 OCR 文字解析成 (stat, kind, value)；认不出返回空。"""
    body = _normalize(text)
    if not body:
        return "", "", 0
    match = _RE_PER_LEVEL.search(body)
    if match:
        return normalize_stat(match.group(1)), "perlevel", int(match.group(2))
    match = _RE_PCT.search(body)
    if match:
        return normalize_stat(match.group(1)), "pct", int(match.group(2))
    match = _RE_FLAT.search(body)
    if match:
        return normalize_stat(match.group(1)), "flat", int(match.group(2))
    match = _RE_ANY.search(body)
    if match:
        stat = normalize_stat(match.group(1))
        if stat != "ALL" and stat not in MAIN_STATS:
            stat = "OTHER"
        return stat, ("pct" if match.group(3) else "flat"), int(match.group(2))
    return "", "", 0


def grade_from_badge(color):
    """由徽章颜色判断 L / U（传 BGR 像素，或传整块徽章）。"""
    array = np.asarray(color, dtype=np.uint8)
    if array.ndim == 1:
        array = array.reshape(1, 1, 3)
    hsv = cv2.cvtColor(array, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    mask = (hsv[:, 1] >= BADGE_S_MIN) & (hsv[:, 2] >= BADGE_V_MIN)
    if not mask.any():
        return "?"
    hue = int(np.median(hsv[mask, 0]))
    if abs(hue - GRADE_L_HUE) <= 6:
        return "L"
    if abs(hue - GRADE_U_HUE) <= 5:
        return "U"
    return "L" if hue > (GRADE_L_HUE + GRADE_U_HUE) / 2 else "U"


def row_boxes(frame):
    """三行的 (徽章框, 文字框)，坐标随画面尺寸缩放。"""
    height, width = frame.shape[:2]
    boxes = []
    for center in ROW_Y:
        y0 = int((center - ROW_H / 2) * height)
        y1 = int((center + ROW_H / 2) * height)
        badge = (int(BADGE_X * width), y0, int(BADGE_W * width), y1 - y0)
        text = (int(TEXT_X0 * width), y0, int((TEXT_X1 - TEXT_X0) * width), y1 - y0)
        boxes.append((badge, text))
    return boxes


def _ocr_text(ocr, crop, upscale=3.0, pad=16):
    """裁图 → 放大 → 四周垫一圈像素 → OCR（小图垫边后识别率明显更高）。"""
    if crop is None or crop.size == 0:
        return ""
    if upscale and abs(upscale - 1.0) > 0.01:
        crop = cv2.resize(crop, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    if pad:
        crop = cv2.copyMakeBorder(crop, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
    result = ocr.ocr(crop)
    if result and result[0]:
        return " ".join(str(item[1][0]) for item in result[0])
    return ""


def read_lines(frame, ocr=None, upscale=3.0, pad=16, store=None, fast=False):
    """读出三行属性（OCR 只识别文字区，等级用徽章颜色）。

    先整行识别；认不出来时再只裁右半段（"属性 +X" 那部分）重试，
    内容越少 PaddleOCR 通常越稳。
    """
    if frame is None or getattr(frame, "size", 0) == 0:
        return []
    if ocr is None:
        import logging

        from paddleocr import PaddleOCR

        logging.getLogger("ppocr").setLevel(logging.ERROR)
        ocr = PaddleOCR(lang="ch", show_log=False)

    lines = []
    for badge, text in row_boxes(frame):
        bx, by, bw, bh = badge
        patch = frame[by:by + bh, bx:bx + bw]
        grade = grade_from_badge(patch) if patch.size else "?"

        tx, ty, tw, th = text
        crop = frame[ty:ty + th, tx:tx + tw]
        width = frame.shape[1]

        if store is not None and fast:
            bits_hex, bits = fingerprint(crop)
            hit = store.lookup(width, bits_hex, bits) if bits_hex else None
            if hit:
                lines.append(PotentialLine(raw=hit.get("raw", [""])[0], grade=grade,
                                           stat=hit["stat"], kind=hit["kind"],
                                           value=hit["value"]))
                continue

        raw = _ocr_text(ocr, crop, upscale=upscale, pad=pad)
        stat, kind, value = parse_line(raw)

        # 整行里出现了"每…級"但属性没认出来：右半段只裁到 "STR +2"，需要补回 perlevel 语义
        per_level_hint = ("每" in raw) and ("級" in raw or "级" in raw)

        if not stat and tw > 40:
            half = crop[:, int(crop.shape[1] * 0.45):]
            raw2 = _ocr_text(ocr, half, upscale=upscale, pad=pad)
            stat2, kind2, value2 = parse_line(raw2)
            if stat2:
                if per_level_hint and kind2 == "flat":
                    kind2 = "perlevel"
                raw, stat, kind, value = raw2, stat2, kind2, value2

        lines.append(PotentialLine(raw=raw, grade=grade, stat=stat, kind=kind, value=value))
        if store is not None and stat:
            store.record(crop, (stat, kind, value), raw, width)
    return lines


def is_useful_main(line, main):
    """自己用的判定：主属性 / 全屬性 / 每9級主属性+2。"""
    if line.kind == "pct":
        if line.stat == main:
            return line.value in PCT_SINGLE
        if line.stat == "ALL":
            return line.value in PCT_ALL
    if line.kind == "perlevel" and line.stat == main:
        return line.value == PER_LEVEL_VALUE
    return False


def judge(lines, main="LUK"):
    """三条都满足才保留。返回 (keep, reason)。"""
    if len(lines) != 3:
        return False, "行数不是 3"
    if any(not line.ok for line in lines):
        return False, "有识别不出的行"

    if all(is_useful_main(line, main) for line in lines):
        return True, f"三条都是{main}可用属性"

    stats = {line.stat for line in lines}
    if len(stats) == 1:
        stat = next(iter(stats))
        if stat != main:
            fits = []
            for line in lines:
                if line.grade != "L":
                    fits.append(False)
                    continue
                if line.kind == "pct":
                    fits.append(line.value in PCT_SINGLE)
                elif line.kind == "perlevel":
                    fits.append(line.value == PER_LEVEL_VALUE)
                else:
                    fits.append(False)
            if all(fits):
                return True, f"三条都是{stat}的L级属性"

    return False, "不满足保留条件"


# ---------------------------------------------------------------- 交互层
#: 粉色魔方图标（窗口内比例，基于 1382×807 实测）
PINK_CUBE_BOX = (200 / 1382, 515 / 807, 250 / 1382, 565 / 807)
#: 「重新設定」按钮
RESET_BTN_BOX = (255 / 1382, 695 / 807, 460 / 1382, 750 / 807)
#: 选中时图标外框的青色像素数量（旧判据，遇到青色方块会误判，已改为看标题）
CYAN_MIN_PIXELS = 50
CYAN_HUE = (80, 105)

#: 模板素材目录（gitignore 里的 screenshots/ 下面）
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "screenshots" / "cube_templates"
#: 每个标签最多留几张图给人工确认
MAX_SAMPLES_PER_LABEL = 5
#: 指纹尺寸（宽 × 高）
FINGERPRINT_SIZE = (60, 12)
#: IoU 容错阈值
FINGERPRINT_IOU = 0.98

#: 「使用货빕」标题栏：显示当前选中的是哪种方块（珍貴/恢復/…）
HEADER_BOX = (175 / 1382, 492 / 807, 570 / 1382, 520 / 807)
#: 点完「重新設定」后等对话框出现（实测 p50 17ms、max 17ms）
DIALOG_WAIT = 0.12
#: 按确认后等新属性渲染（实测 p50 64ms、p95 85ms、max 86ms）
CONFIRM_WAIT = 0.25
#: 确认框里「確認」按钮的位置（窗口内比例）：框打开时这里是亮绿色
CONFIRM_BOX = (605 / 1382, 486 / 807, 690 / 1382, 506 / 807)
CONFIRM_BRIGHT = 110
#: 六个可能的方块槽中心（窗口内 x 比例，槽宽约 27px、间距约 41px）
SLOT_X = tuple(x / 1382 for x in (191, 232, 273, 314, 355, 396))
SLOT_Y = 540 / 807
#: 方块在标题栏里的关键字（实测）
#:   橙色 = 恢復附加方塊
#:   青色 = 絕對附加方塊   （PaddleOCR 一律把「絕」丢掉，读成「對附加方塊」，所以两个写法都认）
#:   粉色 = 珍貴附加方塊
CUBE_KEYWORDS = {
    "pink": ("珍貴", "珍贵"),
    "cyan": ("絕對", "绝对", "對附加"),
    "orange": ("恢復", "恢复"),
}
#: 默认洗粉色（兼容旧调用）
PINK_KEYWORD = CUBE_KEYWORDS["pink"]


def box_pixels(frame, frac_box):
    """比例框 → 像素框 (x0, y0, x1, y1)。"""
    height, width = frame.shape[:2]
    x0, y0, x1, y1 = frac_box
    return int(x0 * width), int(y0 * height), int(x1 * width), int(y1 * height)


def box_center(frame, frac_box):
    x0, y0, x1, y1 = box_pixels(frame, frac_box)
    return (x0 + x1) // 2, (y0 + y1) // 2


def cyan_pixels(frame, frac_box):
    """框内"青色"像素数（选中高亮框）。"""
    x0, y0, x1, y1 = box_pixels(frame, frac_box)
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return 0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = (
        (hsv[:, :, 0] >= CYAN_HUE[0]) & (hsv[:, :, 0] <= CYAN_HUE[1])
        & (hsv[:, :, 1] > 150) & (hsv[:, :, 2] > 150)
    )
    return int(mask.sum())


def grade_count(frame):
    """三行徽章里能认出 L/U 的个数；面板在不在就看它。"""
    count = 0
    for badge, _text in row_boxes(frame):
        bx, by, bw, bh = badge
        patch = frame[by:by + bh, bx:bx + bw]
        if patch.size and grade_from_badge(patch) in ("L", "U"):
            count += 1
    return count


def panel_visible(frame, minimum=2):
    """洗魔方面板是否真的在前台（窗口被遮挡/关闭时为 False，避免白洗）。"""
    return grade_count(frame) >= minimum


def dialog_open(frame):
    """确认框是否已经弹出来（看「確認」按钮那块亮不亮）。"""
    x0, y0, x1, y1 = box_pixels(frame, CONFIRM_BOX)
    region = frame[y0:y1, x0:x1]
    return region.size > 0 and float(region.mean()) > CONFIRM_BRIGHT


def ink_mask(crop):
    """取文字墨迹：背景被压暗到 ~55，文字 >=200，用自适应阈值分开。"""
    if crop is None or getattr(crop, "size", 0) == 0:
        return None
    value = crop.max(axis=2).astype(int)
    threshold = max(180, int(np.median(value)) + 100)
    mask = (value >= threshold).astype(np.uint8)
    return mask if mask.any() else None


def fingerprint(crop, size=FINGERPRINT_SIZE, min_ink=3):
    """墨迹掩膜 → 紧包围盒 → max 池化到固定网格 → 位串。

    用 max 池化而不是面积平均：属性字体的笔画很细，平均之后会整格变 0，
    导致所有行的指纹都一样（撞车）。每格"有墨迹就是 1"才稳。
    """
    mask = ink_mask(crop)
    if mask is None:
        return None, None
    ys, xs = np.nonzero(mask)
    tight = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]

    cols, rows = int(size[0]), int(size[1])
    pad_h = (-tight.shape[0]) % rows
    pad_w = (-tight.shape[1]) % cols
    padded = np.pad(tight, ((0, pad_h), (0, pad_w)), mode="constant")
    blocks = padded.reshape(rows, padded.shape[0] // rows, cols, padded.shape[1] // cols)
    cells = blocks.max(axis=(1, 3)).astype(np.uint8)

    if int(cells.sum()) < min_ink:
        return None, None          # 墨迹太少，当作无效指纹，别登记也别查
    return cells.tobytes().hex(), cells


class TemplateStore:
    """把"这一行是什么属性"记成 指纹 → 标签，并把前几张图存下来供人工看。"""

    def __init__(self, path=None, max_samples=MAX_SAMPLES_PER_LABEL):
        self.path = Path(path) if path else TEMPLATE_DIR / "index.json"
        self.max_samples = max_samples
        self.entries = {}
        self._load()

    def _load(self):
        try:
            self.entries = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self.entries = {}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.entries, ensure_ascii=False, indent=1), encoding="utf-8")

    @staticmethod
    def key(width, bits_hex):
        return f"{int(width)}:{bits_hex}"

    def lookup(self, width, bits_hex, bits=None):
        """先精确命中，再按 IoU 容错（不同帧边缘像素可能有 1~2 位抖动）。"""
        exact = self.entries.get(self.key(width, bits_hex))
        if exact:
            return dict(exact, iou=1.0)
        if bits is None:
            return None
        for name, entry in self.entries.items():
            if not name.startswith(f"{int(width)}:"):
                continue
            mask_hex = entry.get("mask")
            if not mask_hex:
                continue
            expected = FINGERPRINT_SIZE[0] * FINGERPRINT_SIZE[1]
            if len(mask_hex) != expected * 2:
                continue
            # cv2.resize 的 size 是 (宽, 高)，所以数组形状是 (高, 宽)
            stored = np.frombuffer(bytes.fromhex(mask_hex), dtype=np.uint8).reshape(
                FINGERPRINT_SIZE[1], FINGERPRINT_SIZE[0])
            inter = np.logical_and(stored, bits).sum()
            union = np.logical_or(stored, bits).sum()
            iou = float(inter) / union if union else 0.0
            if iou >= FINGERPRINT_IOU:
                return dict(entry, iou=iou)
        return None

    def record(self, crop, parsed, raw, frame_width):
        """登记一次观测：解析成功才写；同一指纹出现不同标签会记 conflicted。"""
        stat, kind, value = parsed
        bits_hex, bits = fingerprint(crop)
        if bits_hex is None or not stat:
            return None
        label = f"{stat}_{kind}_{value}"
        name = self.key(frame_width, bits_hex)
        entry = self.entries.get(name)
        if entry is None:
            entry = {"label": label, "stat": stat, "kind": kind, "value": value,
                     "mask": bits.tobytes().hex(), "count": 0, "samples": [], "raw": []}
            self.entries[name] = entry
        elif entry["label"] != label:
            entry["conflicted"] = sorted(set(entry.get("conflicted", []) + [label]))
        entry["count"] = int(entry.get("count", 0)) + 1
        if raw and raw not in entry["raw"]:
            entry["raw"] = (entry.get("raw") or [])[:4] + [raw]
        if len(entry["samples"]) < self.max_samples:
            folder = self.path.parent / label
            folder.mkdir(parents=True, exist_ok=True)
            filename = folder / f"{time.strftime('%Y%m%d_%H%M%S')}_{entry['count']:03d}.png"
            cv2.imwrite(str(filename), crop)
            entry["samples"].append(str(filename.relative_to(self.path.parent.parent.parent)))
        self._save()
        return entry


def read_header(frame, ocr):
    """读「使用货빕」后面那段文字：当前选中的方块名字。"""
    x0, y0, x1, y1 = box_pixels(frame, HEADER_BOX)
    crop = frame[y0:y1, x0:x1]
    if crop is None or crop.size == 0:
        return ""
    return _ocr_text(ocr, crop, upscale=2.5, pad=12)


def keywords_of(cube):
    """把 cube 参数（名字或别名）换成关键字元组。"""
    value = CUBE_KEYWORDS.get(cube, cube)
    return value if isinstance(value, tuple) else (value,)


def header_matches(frame, ocr, keyword):
    """标题栏里是否出现指定关键字（方块名字，可以是多个别名）。"""
    header = read_header(frame, ocr)
    return any(word in header for word in keywords_of(keyword))


def is_cube_selected(frame, ocr, cube="pink"):
    """指定方块是否已被选中（按标题栏里的名字判断）。"""
    return header_matches(frame, ocr, cube)


def is_pink_selected(frame, ocr):
    """粉色魔方是否已被选中（兼容旧接口）。"""
    return is_cube_selected(frame, ocr, "pink")


def is_selected(frame, ocr=None):
    """兼容旧接口：有 OCR 就按标题判断，没有就退回青色像素。"""
    if ocr is not None:
        return is_pink_selected(frame, ocr)
    return cyan_pixels(frame, PINK_CUBE_BOX) >= CYAN_MIN_PIXELS


class RollError(RuntimeError):
    """洗魔方流程中某一步没成功。"""


class CubeRoller:
    """把"选中粉色魔方 → 点重新設定 → Enter → 读三行"串起来。

    所有外部动作都可注入，方便离线测试：

    :param grab:      ``() -> BGR frame``（游戏窗口截图）
    :param click:     ``(x, y) -> None``
    :param key_api:   :class:`maplebot.keys.Keyboard` 或假实现（只用 tap）
    :param ocr:       PaddleOCR 实例或假实现
    :param sleep:     等待函数
    """

    def __init__(self, grab, click, key_api, ocr=None, sleep=None, main="LUK", roll_key="enter",
                 guard=None, cube="pink"):
        self._grab = grab
        self._click = click
        self._keys = key_api
        self._ocr = ocr
        self._sleep = sleep or time.sleep
        self.main = main
        self.cube = cube              # "pink" / "cyan" / "orange"
        self.roll_key = roll_key      # 实测空格也能触发洗魔方
        self._guard = guard           # () -> bool：游戏窗口是否仍在前台
        self.store = TemplateStore()  # 收集模板素材（指纹 + 每类前几张图）
        self.fast = False             # 表够全后可切成只查表
        self.rolls = 0
        self.history = []

    # ------------------------------------------------------------ 单步
    def select_cube(self, slots=SLOT_X):
        """按标题找指定方块：逐个点槽位，直到标题变成目标名字。

        比按位置/颜色判断可靠：方块数量、顺序、颜色都会变，但名字不会。
        """
        frame = self._grab()
        if is_cube_selected(frame, self._ocr, self.cube):
            return True
        height, width = frame.shape[:2]
        y = int(SLOT_Y * height)
        for frac in slots:
            self._click(int(frac * width), y)
            self._sleep(0.35)
            if is_cube_selected(self._grab(), self._ocr, self.cube):
                return True
        return False

    def select_pink(self, slots=SLOT_X):
        """兼容旧接口：选粉色。"""
        self.cube = "pink"
        return self.select_cube(slots)

    def open_dialog(self, attempts=4):
        """点「重新設定」并确认对话框出现；游戏偶尔会忽略太快的一次点击。"""
        for attempt in range(attempts):
            frame = self._grab()
            x, y = box_center(frame, RESET_BTN_BOX)
            self._click(x, y)
            self._sleep(DIALOG_WAIT)
            if dialog_open(self._grab()):
                return True
            self._sleep(0.20 * (attempt + 1))
        raise RollError("点了重新設定但确认框没有出现")

    def confirm(self):
        self._keys.tap(self.roll_key, hold=0.05)
        self._sleep(CONFIRM_WAIT)  # 实测属性 <=86ms 就渲染完成

    def read(self):
        return read_lines(self._grab(), ocr=self._ocr, store=self.store, fast=self.fast)

    # ------------------------------------------------------------ 整轮
    def roll_once(self):
        """洗一次并返回三行结果；失败抛 :class:`RollError`。"""
        if self._guard is not None and not self._guard():
            raise RollError("游戏窗口不在前台（被遮挡或已切走），停止以免白洗")
        if not panel_visible(self._grab()):
            raise RollError("洗魔方面板不可见（窗口被遮挡或已关闭）")
        if not self.select_cube():
            raise RollError(
                f"{self.cube} 方块没有被选中（标题里没出现 {keywords_of(self.cube)}；"
                "如果背包里没有这种方块，就是这里报错）"
            )
        self.open_dialog()
        self.confirm()
        lines = self.read()
        self.rolls += 1
        keep, reason = judge(lines, main=self.main)
        self.history.append({"roll": self.rolls, "lines": lines, "keep": keep, "reason": reason})
        return lines

    def run_until(self, max_rolls=50, exit_with_esc=True):
        """一直洗到满足条件（或到达次数上限）。

        保留时按一次 Esc 退出洗魔方界面，避免手滑重洗。
        """
        for _ in range(max_rolls):
            lines = self.roll_once()
            keep, reason = self.history[-1]["keep"], self.history[-1]["reason"]
            if keep:
                if exit_with_esc:
                    self._keys.tap("esc", hold=0.04)
                    self._sleep(0.4)
                return True, self.history[-1]
        return False, self.history[-1] if self.history else {}


__all__ = [
    "CubeRoller",
    "PotentialLine",
    "RollError",
    "box_center",
    "box_pixels",
    "cyan_pixels",
    "CONFIRM_WAIT",
    "CUBE_KEYWORDS",
    "MAX_SAMPLES_PER_LABEL",
    "TEMPLATE_DIR",
    "TemplateStore",
    "fingerprint",
    "ink_mask",
    "CONFIRM_BOX",
    "CONFIRM_BRIGHT",
    "DIALOG_WAIT",
    "dialog_open",
    "keywords_of",
    "grade_count",
    "is_cube_selected",
    "header_matches",
    "is_selected",
    "panel_visible",
    "grade_from_badge",
    "is_useful_main",
    "judge",
    "parse_line",
    "read_lines",
    "row_boxes",
]
