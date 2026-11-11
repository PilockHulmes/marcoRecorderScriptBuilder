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

_RE_PCT = re.compile(r"(STR|DEX|INT|LUK|全屬性|全属性)\s*[+＋]\s*(\d+)\s*%")
_RE_FLAT = re.compile(r"(STR|DEX|INT|LUK|全屬性|全属性)\s*[+＋]\s*(\d+)\s*$")
_RE_PER_LEVEL = re.compile(r"每\s*9\s*[級级]\s*(?:為準|为准)?\s*([A-Za-z]{1,3})\s*[+＋]\s*(\d+)")

#: OCR 常把 DEX 認成 DE、LUK 認成 LU，這裡做前綴補全
_STAT_ALIASES = {
    "STR": "STR", "ST": "STR", "S": "STR",
    "DEX": "DEX", "DE": "DEX", "DX": "DEX", "D": "DEX",
    "INT": "INT", "IN": "INT", "I": "INT",
    "LUK": "LUK", "LU": "LUK", "LK": "LUK", "L": "LUK",
}


def normalize_stat(name):
    """把 OCR 出来属性名补全成 STR/DEX/INT/LUK（认不出返回原样）。"""
    key = (name or "").upper().strip()
    return _STAT_ALIASES.get(key, key)
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
        stat = "ALL" if match.group(1) in ("全屬性", "全属性") else match.group(1)
        return stat, "pct", int(match.group(2))
    match = _RE_FLAT.search(body)
    if match:
        stat = "ALL" if match.group(1) in ("全屬性", "全属性") else match.group(1)
        return stat, "flat", int(match.group(2))
    match = _RE_ANY.search(body)
    if match:
        return "OTHER", ("pct" if match.group(3) else "flat"), int(match.group(2))
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


def read_lines(frame, ocr=None, upscale=3.0, pad=16):
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
#: 选中时图标外框的青色像素数量（实测：未选 0，已选 161）
CYAN_MIN_PIXELS = 50
CYAN_HUE = (80, 105)


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


def is_selected(frame):
    """粉色魔方是否已被选中。"""
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

    def __init__(self, grab, click, key_api, ocr=None, sleep=None, main="LUK", roll_key="enter"):
        self._grab = grab
        self._click = click
        self._keys = key_api
        self._ocr = ocr
        self._sleep = sleep or time.sleep
        self.main = main
        self.roll_key = roll_key      # 实测空格也能触发洗魔方
        self.rolls = 0
        self.history = []

    # ------------------------------------------------------------ 单步
    def select_pink(self):
        frame = self._grab()
        if is_selected(frame):
            return True
        x, y = box_center(frame, PINK_CUBE_BOX)
        self._click(x, y)
        self._sleep(0.35)
        return is_selected(self._grab())

    def open_dialog(self):
        frame = self._grab()
        x, y = box_center(frame, RESET_BTN_BOX)
        self._click(x, y)
        self._sleep(0.45)

    def confirm(self):
        self._keys.tap(self.roll_key, hold=0.05)
        self._sleep(0.85)          # 关掉动画后约 0.5s 稳定，留余量

    def read(self):
        return read_lines(self._grab(), ocr=self._ocr)

    # ------------------------------------------------------------ 整轮
    def roll_once(self):
        """洗一次并返回三行结果；失败抛 :class:`RollError`。"""
        if not self.select_pink():
            raise RollError("粉色魔方没有被选中")
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
    "is_selected",
    "grade_from_badge",
    "is_useful_main",
    "judge",
    "parse_line",
    "read_lines",
    "row_boxes",
]
