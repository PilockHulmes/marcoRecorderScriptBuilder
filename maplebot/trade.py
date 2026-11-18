"""跑商活动读图（只读原型）：从游戏截图里读出 SHOP / CARGO 的结构化信息。

这一层**只看图，不碰游戏窗口**：不找窗口、不截屏、不按键。调用方负责把一帧
BGR ``numpy`` 画面递进来（例如 ``config.capture.frame``），本模块返回纯数据。

识别流程：

    frame ──find_shop_window()──> bool
          ──read_row_countdown()──> "01:18"
          ──read_rows()──> [Row(icon_box, name_ocr, buy_price, sell_price, partial), ...]
          ──read_cargo()──> Cargo(coins, weight, capacity)
          ──scroll_handle()──> 0.0(顶) ~ 1.0(底)

几何按 1368×800 的窗口标定（三张 ``screenshots/trading/`` 实测），其它分辨率
按宽/高比例缩放；数字 OCR 在非标定分辨率下只是「尽力而为」，精度会下降。
所有坐标都是**窗口内像素**，与屏幕绝对坐标无关。

识别策略（先跑通，再谈精度）：

- 价格 / 重量 / 金币：固定几何裁出数字条 → 按黄色(数字)+白色(单位/斜杠)
  二值化成黑字白底 → PaddleOCR 只做识别（``det=False``）→ 正则取数字；
- 名字：同样裁固定条，OCR 结果只作参考。十二像素的繁体字 OCR 本来就不稳，
  后续会用 45 个图标模板做真正识别，这里先给一个可用的近似值；
- 图标：**不做识别**，只返回槽位 bbox，留给下一阶段的模板匹配；
- 滚动条：橙色滑块的颜色阈值 + 连通域，按滑块顶端在轨道里的位置算比例。
"""

from __future__ import annotations

from . import paths as paths_module

import argparse
import json
import hashlib
import logging
import re
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

from . import digits as digits_module

# ---------------------------------------------------------------- 几何常量
#: 标定用的窗口尺寸。三张截图都是 1368×800（任务书里的 1382×807 是含边框的
#: 窗口外尺寸，截图画布是客户区）。
BASE_WIDTH = 1368.0
BASE_HEIGHT = 800.0

#: SHOP 窗口**内容区**（不含外框）：x 415..651，y 223..568。
#: 这是 (x, y, w, h)，单位是 @1368×800 的像素；`find_shop_window` 用它判断
#: 标题和图标槽，`read_rows` 用它裁行。
# 玩家给的截图是整窗（1368x800，含标题栏）；实时抓帧是客户区（1366x768）。
# 几何常量都按整窗标定，所以喂客户区帧时要先减去这个偏移，不垫像素。
WINDOW_FRAME_SIZE = (1368, 800)
CLIENT_OFFSET = (1, 32)


def client_offset(frame):
    h, w = frame.shape[:2]
    if (w, h) == WINDOW_FRAME_SIZE:
        return 0, 0
    return CLIENT_OFFSET


def crop_box(frame, x, y, w, h):
    dx, dy = client_offset(frame)
    x0 = max(0, x - dx)
    y0 = max(0, y - dy)
    return frame[y0:y0 + h, x0:x0 + w]


SHOP_BOX = (415, 223, 236, 345)

#: 商品列表视口：标题栏下沿到窗口底边（y 281..568）。
LIST_BOX = (415, 281, 236, 287)

#: 每一行（图标槽顶边）的 y。行距固定 87 px；第 4 行只露出 ~15 px。
ROW_TOPS = (292, 379, 466, 553)
ROW_PITCH = 87

#: 图标槽：x 437..500，63×63。
ICON_BOX = (437, 292, 63, 63)

#: 商品名文字条（相对每一行顶边）。
NAME_BOX = (505, 292, 100, 17)

#: 买价 / 卖价数字条（相对每一行顶边）。右边留到 573，避开后面的「個」。
PRICE_BOX = (535, 292, 38, 16)
BUY_DY = 29
SELL_DY = 55

#: 倒计时数字条（「01:18」）。
COUNTDOWN_BOX = (580, 252, 65, 22)

#: CARGO 窗口内容区。
CARGO_BOX = (672, 223, 279, 345)

#: 金币数量 / 当前重量的数字条。
# CARGO 顶部两行数字的取值框（@1368x800 整窗坐标）。
# 两行文字在两种布局里 y 相同，只有 x 不同：
#   只开货舱（面板居中） -> x≈670
#   商店开着（面板在右） -> x≈802
CARGO_COINS_ONLY = (640, 232, 120, 18)
CARGO_WEIGHT_ONLY = (620, 256, 140, 16)
CARGO_COINS_SHOP = (750, 236, 122, 18)
CARGO_WEIGHT_SHOP = (780, 256, 80, 16)
COINS_BOX = CARGO_COINS_SHOP
WEIGHT_BOX = (775, 254, 92, 22)

#: 滚动条：轨道 ROI、滑块颜色、滑块顶端在 0%/100% 时的 y。
SCROLL_ROI = (628, 280, 22, 292)
SCROLL_TOP_Y = 295
SCROLL_BOTTOM_Y = 562

#: SHOP 标题「SHOP」的黄字区域（用来确认窗口真的在）。
TITLE_BOX = (535, 208, 37, 16)

#: 一行的图标槽只要超过这个亮度比例就认为有商品（空格子是深棕色）。
ROW_PRESENT_LIGHT = 0.08

#: 价格 / 数字的 OCR 放大倍数。数字原图只有 ~10 px 高。
OCR_UPSCALE = 5
NAME_UPSCALE = 6


class TradeParseError(RuntimeError):
    """图里没有可读的 SHOP / CARGO 信息。"""


class OcrUnavailable(RuntimeError):
    """PaddleOCR 没装好或模型不可用。"""


@dataclass(frozen=True)
class Row:
    """一条商品。

    :param icon_box: 图标槽 ``(x, y, w, h)``（窗口坐标）；partial 时仍是完整
                     的逻辑槽位，方便下一阶段按槽位取图。
    :param name_ocr: 商品名的 OCR 结果（可能不准，仅供调试）。
    :param buy_price: 买价；partial 行读不到时为 None。
    :param sell_price: 卖价；partial 行读不到时为 None。
    :param partial: 这一行被列表底边裁掉了（通常是最底下第 4 行）。
    """

    icon_box: tuple
    name_ocr: str
    buy_price: int | None
    sell_price: int | None
    partial: bool


@dataclass(frozen=True)
class Cargo:
    """CARGO 窗口顶部的三项信息。"""

    coins: int
    weight: int
    capacity: int


# ---------------------------------------------------------------- 基础工具
def _empty(frame):
    return frame is None or getattr(frame, "size", 0) == 0 or getattr(frame, "ndim", 0) != 3


def _scale(frame):
    """返回 (sx, sy)：把 @1368×800 的常量映射到当前画面。"""
    height, width = frame.shape[:2]
    return width / BASE_WIDTH, height / BASE_HEIGHT


def _box(frame, box):
    """把基准像素 box 缩放并裁到画面内，返回 ``(x, y, w, h)``。"""
    height, width = frame.shape[:2]
    x, y, w, h = box
    # 实时帧是同一窗口的客户区（少 2x32 的边框和标题栏），界面没缩放，用平移。
    if (width + 2, height + 32) == WINDOW_FRAME_SIZE:
        return (max(0, int(x - CLIENT_OFFSET[0])), max(0, int(y - CLIENT_OFFSET[1])),
                int(w), int(h))
    sx, sy = _scale(frame)
    x0 = max(0, min(width, int(round(x * sx))))
    y0 = max(0, min(height, int(round(y * sy))))
    x1 = max(0, min(width, int(round((x + w) * sx))))
    y1 = max(0, min(height, int(round((y + h) * sy))))
    return x0, y0, x1 - x0, y1 - y0


def _crop_at(frame, box, scale):
    """从**原生帧**按缩放比裁一块（``box`` 仍是 1366 的窗口坐标）。

    1920 这类放大过的画面：先把窗口坐标减掉边框偏移，再乘缩放比，
    直接从原图裁——不经过"缩回 1366"那一步，位图字体才不会被重采样打散。
    """
    if frame is None or not scale:
        return None
    try:
        ox, oy = client_offset(frame)
        x = int(round((box[0] - ox) * scale))
        y = int(round((box[1] - oy) * scale))
        w = int(round(box[2] * scale))
        h = int(round(box[3] * scale))
        if w <= 0 or h <= 0:
            return None
        return frame[y:y + h, x:x + w]
    except Exception:
        return None


def _crop(frame, box):
    x, y, w, h = _box(frame, box)
    if w <= 0 or h <= 0:
        return None
    return frame[y:y + h, x:x + w]


def _split(frame, box):
    """裁 box，返回 ``(crop, (x, y, w, h))``。"""
    rect = _box(frame, box)
    x, y, w, h = rect
    if w <= 0 or h <= 0:
        return None, rect
    return frame[y:y + h, x:x + w], rect


def _color_masks(crop):
    """返回 (yellow, white, light) 三个布尔 mask。

    BGR 顺序容易写反，这里统一拆成 r/g/b 再判断。
    """
    b = crop[:, :, 0].astype(np.int16)
    g = crop[:, :, 1].astype(np.int16)
    r = crop[:, :, 2].astype(np.int16)
    yellow = (r >= 150) & (g >= 100) & (b <= 130)
    white = (r >= 140) & (g >= 140) & (b >= 140)
    light = yellow | white
    return yellow, white, light


def _ocr_image(crop, mode="light"):
    """把裁图变成「黑字白底」的 OCR 输入；mode: light / white / yellow / raw。"""
    if mode == "raw":
        return crop
    yellow, _white, light = _color_masks(crop)
    if mode == "yellow":
        mask = yellow
    elif mode == "white":
        # 商品名是纯白字，收紧阈值可以把图标槽的浅灰边挡在外面。
        b = crop[:, :, 0].astype(np.int16)
        g = crop[:, :, 1].astype(np.int16)
        r = crop[:, :, 2].astype(np.int16)
        mask = (r >= 145) & (g >= 145) & (b >= 145)
    else:
        mask = light
    src = np.full_like(crop, 255, dtype=np.uint8)
    src[mask] = (0, 0, 0)
    return src


# ---------------------------------------------------------------- OCR
_OCR_ENGINE = None
_OCR_LOCK = threading.Lock()


def _get_ocr():
    """惰性初始化 PaddleOCR（第一次调用 ~1 s，之后复用）。"""
    global _OCR_ENGINE
    if _OCR_ENGINE is not None:
        return _OCR_ENGINE
    with _OCR_LOCK:
        if _OCR_ENGINE is not None:
            return _OCR_ENGINE
        try:
            from paddleocr import PaddleOCR
        except Exception as exc:  # pragma: no cover - 取决于环境
            raise OcrUnavailable(f"PaddleOCR 不可用：{exc}") from exc
        logging.getLogger("ppocr").setLevel(logging.ERROR)
        try:
            _OCR_ENGINE = PaddleOCR(use_angle_cls=False, lang="ch", show_log=False)
        except Exception as exc:  # pragma: no cover - 取决于模型是否已缓存
            raise OcrUnavailable(f"PaddleOCR 初始化失败：{exc}") from exc
    return _OCR_ENGINE


def _first_text(result):
    """从 PaddleOCR 的几种返回结构里取出第一段文字。"""
    if not result:
        return ""
    first = result[0]
    if first is None:
        return ""
    if isinstance(first, dict):
        texts = first.get("rec_texts") or first.get("text") or []
        return str(texts[0]) if texts else ""
    if isinstance(first, (list, tuple)):
        first = first[0] if first else ""
    if isinstance(first, (list, tuple)):
        first = first[0] if first else ""
    return str(first)


def _ocr_text(crop, mode="light", upscale=OCR_UPSCALE, interpolation=cv2.INTER_CUBIC):
    """对一小块图做「只识别」OCR，返回原始文本（可能带空格/噪声）。"""
    if crop is None or crop.size == 0:
        return ""
    engine = _get_ocr()
    src = _ocr_image(crop, mode)
    src = cv2.resize(src, None, fx=upscale, fy=upscale, interpolation=interpolation)
    try:
        result = engine.ocr(src, det=False, rec=True, cls=False)
    except TypeError:  # 兼容没有 kwargs 的旧/新版本
        result = engine.ocr(src)
    return _first_text(result).strip()


def _first_int(text):
    match = re.search(r"\d+", text or "")
    return int(match.group()) if match else None


def _parse_countdown(text):
    match = re.search(r"(\d{1,2})\s*:\s*(\d{1,2})", text or "")
    if not match:
        return ""
    return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}"


# ---------------------------------------------------------------- 窗口 / 滚动条
def _thumb(frame):
    """在滚动条 ROI 里找橙色滑块，返回 ``(x, y, w, h)`` 或 None。"""
    crop, rect = _split(frame, SCROLL_ROI)
    if crop is None:
        return None
    b = crop[:, :, 0].astype(np.int16)
    g = crop[:, :, 1].astype(np.int16)
    r = crop[:, :, 2].astype(np.int16)
    # 实测滑块 BGR=(0,170,255)；比 HSV 更直接，且轨道 ROI 里没有别的橙色。
    mask = ((r >= 180) & (g >= 110) & (g <= 215) & (b <= 90)).astype(np.uint8)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    sx, _sy = _scale(frame)
    min_area = max(6, int(round(20 * sx * sx)))
    best = None
    for i in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[i])
        if area < min_area or h < 8 or w > 12 or h > crop.shape[0]:
            continue
        if best is None or area > best[0]:
            best = (area, x + rect[0], y + rect[1], w, h)
    if best is None:
        return None
    _area, x, y, w, h = best
    return x, y, w, h


def find_shop_window(frame) -> bool:
    """画面里是不是开着跑商 SHOP 窗口。

    三个锚点同时成立才算：
    1. 顶部「SHOP」黄字（窗口标题，实测 21 个黄像素）；
    2. 蓝色标题栏（区分天空/其它面板）；
    3. 第 1 行图标槽的亮色背景。

    这样即使周围有蓝天、其他 NPC 面板或橙色特效，也不会误判。
    """
    if _empty(frame):
        return False
    sx, sy = _scale(frame)
    area_scale = sx * sy

    title = _crop(frame, TITLE_BOX)
    if title is None:
        return False
    yellow, _white, _light = _color_masks(title)
    if int(yellow.sum()) < max(3, int(round(5 * area_scale))):
        return False

    header = _crop(frame, (415, 228, 236, 50))
    if header is None:
        return False
    b = header[:, :, 0].astype(np.int16)
    g = header[:, :, 1].astype(np.int16)
    r = header[:, :, 2].astype(np.int16)
    blue = (b > 40) & (b < 150) & (b > r + 15) & (b > g + 5)
    if blue.mean() < 0.30:
        return False

    icon, _rect = _split(frame, ICON_BOX)
    if icon is None:
        return False
    _yellow, _white, light = _color_masks(icon)
    return bool(light.mean() >= 0.20)


def scroll_handle(frame) -> float | None:
    """橙色滑块在轨道里的位置：0.0=顶，1.0=底；找不到滑块返回 None。

    比例用滑块**顶端**算：``(y - 295) / (562 - 295 - 滑块高)``。
    这样滑块高度随商品数量变化时，到底仍然精确等于 1.0。
    """
    if _empty(frame):
        return None
    thumb = _thumb(frame)
    if thumb is None:
        return None
    _x, y, _w, h = thumb
    sx, sy = _scale(frame)
    top = SCROLL_TOP_Y * sy
    bottom = SCROLL_BOTTOM_Y * sy
    travel = bottom - top - h
    if travel <= 0:
        return None
    ratio = (y - top) / travel
    return float(min(1.0, max(0.0, ratio)))


# ---------------------------------------------------------------- 倒计时 / 行
#: 上次找到 CARGO 标题的位置（按画面尺寸记）：全屏匹配很贵，记住后只查附近
_CARGO_WINDOW_HINT = {}


def find_cargo_window(frame) -> bool:
    """画面里是不是开着货舱窗口（用面板标题 "CARGO" 做模板）。

    模板只有 CARGO 文字，**不含玩家角色外观**——旧的 cargo_header.png 是从
    我的角色画面截的，别人用会匹配不上，已删除。

    标题位置是固定的：先在上次的位置附近找（<1 ms），找不到才全屏匹配（约 40 ms）。
    """
    if _empty(frame):
        return False
    from . import anchors as anchors_module

    patch = anchors_module.load_patches().get("cargo")
    if patch is None or patch.shape[0] >= frame.shape[0]:
        return False
    height, width = frame.shape[:2]
    hint = _CARGO_WINDOW_HINT.get((width, height))
    if hint is not None:
        pad = 12
        x0 = max(0, hint[0] - pad)
        y0 = max(0, hint[1] - pad)
        window = frame[y0:y0 + patch.shape[0] + 2 * pad,
                       x0:x0 + patch.shape[1] + 2 * pad]
        if (window.shape[0] >= patch.shape[0]
                and window.shape[1] >= patch.shape[1]):
            result = cv2.matchTemplate(window, patch, cv2.TM_CCOEFF_NORMED)
            if result.size and float(result.max()) >= 0.85:
                _CARGO_WINDOW_HINT[(width, height)] = (hint[0], hint[1])
                return True
    try:
        result = cv2.matchTemplate(frame, patch, cv2.TM_CCOEFF_NORMED)
    except Exception:
        return False
    if not result.size:
        return False
    _min, score, _loc, loc = cv2.minMaxLoc(result)
    if float(score) >= 0.85:
        _CARGO_WINDOW_HINT[(width, height)] = (loc[0], loc[1])
        return True
    return False


def _countdown_text(groups):
    """两组数字 -> ``"01:18"``；不是合法倒计时返回空串。"""
    if len(groups) != 2:
        return ""
    try:
        minutes, seconds = int(groups[0]), int(groups[1])
    except Exception:
        return ""
    if 0 <= minutes <= 99 and 0 <= seconds < 60:
        return f"{minutes:02d}:{seconds:02d}"
    return ""


def read_row_countdown(frame, native=None) -> str:
    """读「商品/價格變動中止」下面的倒计时，返回 ``"01:18"``；读不到返回空串。

    ``native=(原帧, 缩放比)``：给了就先从原图按原生尺度读（放大过的画面
    用 12/14px 的位图字体，缩回 1366 会认错），读不到再走基准视图。
    """
    if _empty(frame):
        return ""
    if native is not None:
        native_frame, scale = native
        raw = _crop_at(native_frame, COUNTDOWN_BOX, scale)
        if raw is not None:
            groups = digits_module.read_groups(
                raw, family=digits_module.family_for("fat", scale),
                kind="gold", mode="gap")
            text = _countdown_text(groups)
            if text:
                return text
    crop = _crop(frame, COUNTDOWN_BOX)
    if crop is None:
        return ""
    groups = digits_module.read_groups(crop, family="fat", kind="gold", mode="gap")
    if len(groups) == 2:
        try:
            minutes, seconds = int(groups[0]), int(groups[1])
            if 0 <= minutes <= 99 and 0 <= seconds < 60:
                return f"{minutes:02d}:{seconds:02d}"
        except Exception:
            pass
    text = _ocr_text(crop, mode="light")
    countdown = _parse_countdown(text)
    if countdown:
        return countdown
    # 二值化偶尔会把冒号吃掉（"0118"），用原图再兜一次。
    return _parse_countdown(_ocr_text(crop, mode="raw"))


def _row_present(frame, icon_box, clip_bottom=None):
    """图标槽里有没有内容：槽位背景是浅灰，空格子是深棕色。

    ``clip_bottom`` 是列表视口底边（缩放后的像素）：第 4 行只剩十几像素时，
    不能把窗口外框的亮色算进来，否则空格子会被当成商品。
    """
    x, y, w, h = icon_box
    if clip_bottom is not None:
        h = max(0, min(y + h, clip_bottom) - y)
    if w <= 0 or h <= 0:
        return False
    crop = frame[y:y + h, x:x + w]
    if crop.size == 0:
        return False
    _yellow, _white, light = _color_masks(crop)
    return bool(light.mean() >= ROW_PRESENT_LIGHT)


def _read_price(frame, top, dy, native=None):
    box = (PRICE_BOX[0], top + dy, PRICE_BOX[2], PRICE_BOX[3])
    if native is not None:
        native_frame, scale = native
        raw = _crop_at(native_frame, box, scale)
        if raw is not None:
            value = digits_module.read_number(
                raw, family=digits_module.family_for("thin", scale), kind="gold")
            if value is not None:
                return value
    crop = _crop(frame, box)
    if crop is None:
        return None
    value = digits_module.read_number(crop, family="thin", kind="gold")
    if value is not None:
        return value
    # 模板认不出（新数字 / 渲染变化）才退回 OCR
    value = _first_int(_ocr_text(crop, mode="yellow"))
    if value is not None:
        return value
    return _first_int(_ocr_text(crop, mode="raw"))


#: 倒计时到期时刻允许的抖动（秒）。超过这个变化就认为商店刷新过。
#: 负重上限：游戏的固定值，不读画面（白字常被特效遮挡）
CAPACITY = 135

CACHE_DEADLINE_TOLERANCE = 5.0


class FrameCache:
    """按"像素摘要"复用上一次的解析结果（LRU）。

    只存解析后的结果（几十字节），不存原图。默认 8 条，
    因为列表滚动就那几种状态，来回滚也能命中。
    """

    def __init__(self, max_entries=8):
        self.max_entries = max_entries
        self._items = {}
        self._order = []

    def get(self, key):
        if key in self._items:
            self._order.remove(key)
            self._order.append(key)
            return self._items[key]
        return None

    def put(self, key, value):
        if key in self._items:
            self._order.remove(key)
        self._items[key] = value
        self._order.append(key)
        while len(self._order) > self.max_entries:
            oldest = self._order.pop(0)
            self._items.pop(oldest, None)

    def clear(self):
        self._items.clear()
        self._order.clear()

    def __len__(self):
        return len(self._items)


def _region_digest(frame, boxes):
    """把几个区域拼起来算一个短摘要。"""
    digest = hashlib.blake2b(digest_size=8)
    for box in boxes:
        crop = _crop(frame, box)
        if crop is not None:
            digest.update(crop.tobytes())
    return digest.digest()


def _icon_boxes(frame):
    """三行图标的框（用来判断有没有滚动 / 换货）。"""
    boxes = []
    for top in ROW_TOPS[:3]:
        boxes.append((ICON_BOX[0], top, ICON_BOX[2], ICON_BOX[3]))
    return boxes


def read_rows(frame, cache=None, cache_tag="", deadline=None, native=None) -> list[Row]:
    """读商品列表，最多 4 条；SHOP 不在时返回空列表。

    第 4 行通常被视口底边裁掉，这时 ``partial=True``，也读不到价格。
    """
    if _empty(frame) or not find_shop_window(frame):
        return []

    cache_key = None
    if cache is not None:
        digest = _region_digest(frame, _icon_boxes(frame))
        cache_key = ("rows", cache_tag, digest)
        entry = cache.get(cache_key)
        if entry is not None:
            same_cycle = (deadline is None or entry.get("deadline") is None
                          or abs(entry["deadline"] - deadline) <= CACHE_DEADLINE_TOLERANCE)
            if same_cycle:
                # 命中是常态（每 0.2 秒一次），不打印，免得刷屏
                return list(entry["rows"])
            reason = "倒计时跳变（商店刷新过）"
        else:
            reason = "第一次读到这个列表状态"
    rows = []
    list_box = _box(frame, LIST_BOX)
    list_bottom = list_box[1] + list_box[3]
    for top in ROW_TOPS:
        icon_box = _box(frame, (ICON_BOX[0], top, ICON_BOX[2], ICON_BOX[3]))
        if icon_box[1] >= list_bottom:
            break
        if not _row_present(frame, icon_box, clip_bottom=list_bottom):
            continue

        partial = icon_box[1] + icon_box[3] > list_bottom
        # 商品名不再 OCR：45 个商品全靠图标识别，名字只给"学名字"用，已经关掉。
        # 这一步原来每次要 118 ms（每次读商店 29%），去掉后读一次快 3 成。
        name = ""

        if partial:
            buy = sell = None
        else:
            buy = _read_price(frame, top, BUY_DY, native=native)
            sell = _read_price(frame, top, SELL_DY, native=native)
        rows.append(Row(icon_box=icon_box, name_ocr=name,
                        buy_price=buy, sell_price=sell, partial=partial))
    if cache_key is not None and rows:
        cache.put(cache_key, {"rows": list(rows), "deadline": deadline})
        print(f"[cache] miss {reason} -> 重读价格（{len(rows)} 行）", flush=True)
    return rows


# ---------------------------------------------------------------- CARGO
def _longest_int(text):
    """取文本里最长的连续数字（金币是右对齐的，放宽后可能有杂字）。"""
    runs = re.findall(r"\d+", text or "")
    if not runs:
        return None
    return int(max(runs, key=len))


def _gold_only(crop):
    """只留金色像素（数字是金色、标签是白色），返回裁好的小图。

    找不到金色就原样返回，交给后面的兜底逻辑。
    """
    if crop is None or crop.size == 0:
        return crop
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (12, 90, 150), (40, 255, 255))
    cols = mask.any(axis=0)
    rows = mask.any(axis=1)
    if not cols.any() or not rows.any():
        return crop
    xs = np.where(cols)[0]
    ys = np.where(rows)[0]
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    if x1 - x0 < 3 or y1 - y0 < 5:
        return crop
    return crop[y0:y1, x0:x1]


def _longest_int(text):
    """取文本里最长的连续数字（放宽取数框后可能有杂字）。"""
    runs = re.findall(r"\d+", text or "")
    if not runs:
        return None
    return int(max(runs, key=len))


def _digits_by_gap(crop):
    """把金色数字按空隙切开分别识别，避免千位分隔的空格被读成数字。

    游戏里 3518 显示成「3 518」：整段 OCR 会把空格当成 1，读成 31518。
    这里找到内部最宽的一段空白，左右分别识别再拼起来。
    """
    if crop is None or crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (12, 90, 150), (40, 255, 255))
    cols = (mask > 0).sum(axis=0)
    if cols.max() == 0:
        return None
    # 内部空隙：连续为 0 的列
    gaps = []
    start = None
    for index, value in enumerate(cols):
        if value == 0:
            if start is None:
                start = index
        elif start is not None:
            gaps.append((start, index - 1))
            start = None
    inner = [(a, b) for a, b in gaps if a > 0 and b < len(cols) - 1]
    if not inner:
        return None
    a, b = max(inner, key=lambda gap: gap[1] - gap[0])
    left, right = crop[:, :a], crop[:, b + 1:]
    pieces = []
    for part in (left, right):
        text = _ocr_text(part, mode="light") or _ocr_text(part, mode="raw") or ""
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            return None
        pieces.append(digits)
    return int("".join(pieces))


def _digits_count_matches(crop, value):
    """金色区域里的字形个数，和识别出来的位数是否一致。

    游戏用空格分千位（3 518），整段 OCR 会把空格当数字，
    位数一多就对不上——这时候宁可返回 None（界面显示「金 ?」）。
    """
    try:
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (12, 90, 150), (40, 255, 255))
        cols = (mask > 0).sum(axis=0)
        runs, start = 0, None
        for index, count in enumerate(cols):
            if count > 0 and start is None:
                start = index
            elif count == 0 and start is not None:
                if index - start >= 3:
                    runs += 1
                start = None
        if start is not None and len(cols) - start >= 3:
            runs += 1
        if runs <= 1:
            return True
        return runs == len(str(value))
    except Exception:
        return True


#: 金币数字的字距（像素）。实测 1 位 7px、4 位 32px，按 8px 一位切。
COIN_DIGIT_PITCH = 8.0
#: 相邻两位之间最多这么大的空隙还算同一个数字
COIN_DIGIT_GAP = 5


def _rightmost_gold_run(strip):
    """从右往左把"连在一起的数字"合成一段，返回 (x0, x1)。

    数字是金色的、贴在最右边；但每位之间的空隙有 3~4 像素，
    所以先把空隙 <= COIN_DIGIT_GAP 的相邻段合并，再从右边取一整块。
    """
    if strip is None or strip.size == 0:
        return None
    hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (12, 90, 150), (40, 255, 255))
    cols = (mask > 0).any(axis=0)
    runs, start = [], None
    for index, value in enumerate(cols):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append([start, index - 1])
            start = None
    if start is not None:
        runs.append([start, len(cols) - 1])
    if not runs:
        return None
    merged = [runs[-1]]
    for run in reversed(runs[:-1]):
        if merged[0][0] - run[1] - 1 <= COIN_DIGIT_GAP:
            merged[0][0] = run[0]
        else:
            break
    return merged[0][0], merged[0][1] + 1


def _digits_by_width(strip):
    """按固定字宽把金币数字切成一位一位，分别识别再拼起来。

    整段 OCR 会把"3 518"里的空格读成 1、把"90"读成 9，
    逐位识别能避开这类问题；任何一位读不出来就返回 None（显示「金 ?」）。
    """
    run = _rightmost_gold_run(strip)
    if run is None:
        return None
    x0, x1 = run
    width = x1 - x0
    count = int(round(width / COIN_DIGIT_PITCH))
    if count < 1 or count > 8:
        return None
    step = width / count
    digits = []
    for index in range(count):
        left = int(round(x0 + index * step)) - 2
        right = int(round(x0 + (index + 1) * step)) + 2
        cell = strip[:, max(0, left):min(strip.shape[1], right)]
        if cell is None or cell.size == 0:
            return None
        big = cv2.resize(cell, (cell.shape[1] * 4, cell.shape[0] * 4),
                         interpolation=cv2.INTER_NEAREST)
        text = _ocr_text(big, mode="light") or _ocr_text(big, mode="raw") or ""
        found = [ch for ch in text if ch.isdigit()]
        if len(found) != 1:
            return None
        digits.append(found[0])
    return int("".join(digits))


def _digits_of_run(strip):
    """逐位识别；某几位粘在一起（切不开）时，整段再认一次做兜底。"""
    value = _digits_by_width(strip)
    if value is not None:
        return value
    run = _rightmost_gold_run(strip)
    if run is None:
        return None
    x0, x1 = run
    count = int(round((x1 - x0) / COIN_DIGIT_PITCH))
    if count < 2:
        return None            # 只有一位时不敢整段认，宁可当未知
    crop = strip[:, x0:x1]
    for mode in ("light", "raw"):
        text = _ocr_text(crop, mode=mode) or ""
        found = [ch for ch in text if ch.isdigit()]
        if len(found) == count:
            return int("".join(found))
    return None


def _finish_cargo(coins, weight, capacity=None, cache=None, cargo_key=None):
    result = Cargo(coins=coins, weight=int(weight), capacity=CAPACITY)
    if cache is not None and cargo_key is not None:
        cache.put(cargo_key, result)
    return result


def read_cargo(frame, profile="shop", cache=None, native=None) -> Cargo:
    """读 CARGO 顶部的金币 / 当前重量 / 容量。

    ``profile``：``shop`` = 商店开着（货舱在右边）；``only`` = 只开货舱（居中）。
    图里没有 SHOP/CARGO 或 OCR 读不出来时抛 :class:`TradeParseError`。
    """
    if _empty(frame):
        raise TradeParseError("没有画面")
    if profile != "only" and not find_shop_window(frame):
        raise TradeParseError("没有检测到 SHOP 窗口")

    if profile == "only":
        coins_box, weight_box = CARGO_COINS_ONLY, CARGO_WEIGHT_ONLY
    else:
        coins_box, weight_box = CARGO_COINS_SHOP, CARGO_WEIGHT_SHOP

    cargo_key = None
    if cache is not None:
        digest = _region_digest(frame, (coins_box, weight_box))
        cargo_key = ("cargo", profile, digest)
        entry = cache.get(cargo_key)
        if entry is not None:
            return entry
    # 放大过的画面（1920）：先从原图按原生尺度读一遍，字体不会被重采样打散
    if native is not None:
        native_frame, scale = native
        family = digits_module.family_for("fat", scale)
        raw_coins = _crop_at(native_frame, coins_box, scale)
        raw_weight = _crop_at(native_frame, weight_box, scale)
        if raw_coins is not None and raw_weight is not None:
            coins = digits_module.read_number(raw_coins, family=family, kind="gold")
            groups = digits_module.read_groups(raw_weight, family=family, kind="gold")
            weight = int(groups[0]) if groups and groups[0].isdigit() else None
            if coins is not None and weight is not None:
                result = Cargo(coins=coins, weight=weight, capacity=CAPACITY)
                if cargo_key is not None:
                    cache.put(cargo_key, result)
                return result

    coins_crop = _crop(frame, coins_box)
    weight_crop = _crop(frame, weight_box)
    if coins_crop is None or weight_crop is None:
        raise TradeParseError("CARGO 数字区域超出画面")

    # 模板匹配一律在**原图**上做（字体高度是 10px）
    raw_coins, raw_weight = coins_crop, weight_crop
    coins = digits_module.read_number(raw_coins, family="fat", kind="gold")
    weight_groups = digits_module.read_groups(raw_weight, family="fat", kind="gold")

    # 后面几条兜底是给 OCR 用的：单独货舱的字更小，先放大 3 倍
    if profile == "only":
        coins_crop = cv2.resize(
            coins_crop, (coins_crop.shape[1] * 3, coins_crop.shape[0] * 3),
            interpolation=cv2.INTER_CUBIC)
        weight_crop = cv2.resize(
            weight_crop, (weight_crop.shape[1] * 3, weight_crop.shape[0] * 3),
            interpolation=cv2.INTER_CUBIC)
    else:
        coins_crop = _gold_only(coins_crop)
    if coins is None:
        coins = _digits_of_run(coins_crop)
    if coins is None:
        coins = _longest_int(_ocr_text(coins_crop, mode="light"))
    if coins is None:
        coins = _digits_by_gap(coins_crop)
    if coins is not None and not _digits_count_matches(coins_crop, coins):
        coins = None          # 位数对不上（3 518 读成 31518）就别硬用
    if coins is None:
        # 数字是描边字体，二值化常把 0 认成"口"；原图再试一次
        coins = _longest_int(_ocr_text(coins_crop, mode="raw"))
    # 当前负重是**金色**数字，和金币同一套模板；"/135" 那部分才是白色，不读。
    weight_value = None
    if weight_groups and weight_groups[0].isdigit():
        weight_value = int(weight_groups[0])

    if weight_value is None:
        # 兜底：白色字 / 被特效遮挡时退回 OCR
        weight_text = _ocr_text(weight_crop, mode="light")
        match = re.search(r"(\d+)\s*/\s*(\d+)", weight_text)
        if match is None:
            weight_text = _ocr_text(weight_crop, mode="raw")
            match = re.search(r"(\d+)\s*/\s*(\d+)", weight_text)
        if match is not None:
            weight_value = int(match.group(1))

    if coins is None or weight_value is None:
        raise TradeParseError(f"CARGO 读不出来：coins={coins!r} weight={weight_value!r}")
    # 容量是游戏的固定值 135（只有极新手的角色更低，不在考虑范围）。
    # 那一半是白字、经常被武器特效盖住，不去读它，直接写死。
    result = Cargo(coins=coins, weight=int(weight_value), capacity=CAPACITY)
    if cargo_key is not None:
        cache.put(cargo_key, result)
    return result


# ---------------------------------------------------------------- 汇总 / CLI
def snapshot(frame) -> dict:
    """把一帧解析成可直接 json 的 dict（CLI 与调试共用）。"""
    shop = find_shop_window(frame)
    payload = {
        "shop": shop,
        "countdown": "",
        "scroll": scroll_handle(frame) if shop else None,
        "cargo": None,
        "rows": [],
    }
    if not shop:
        return payload
    try:
        payload["countdown"] = read_row_countdown(frame)
        try:
            payload["cargo"] = asdict(read_cargo(frame))
        except TradeParseError as exc:
            payload["cargo_error"] = str(exc)
        payload["rows"] = [asdict(row) for row in read_rows(frame)]
    except OcrUnavailable as exc:
        payload["ocr_error"] = str(exc)
    return payload


def load_image(path):
    """读图片；``cv2.imread`` 在 Windows 上不支持中文路径，这里走 numpy。"""
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m maplebot.trade",
        description="离线验证：读一张跑商截图，打印 SHOP / CARGO 的解析结果（JSON）。",
    )
    parser.add_argument("image", help="截图路径（整窗画面）")
    parser.add_argument("--indent", type=int, default=2, help="JSON 缩进，默认 2")
    args = parser.parse_args(argv)

    path = Path(args.image)
    if not path.is_file():
        print(f"找不到图片：{path}", file=sys.stderr)
        return 2
    frame = load_image(path)
    if frame is None:
        print(f"图片读不出来：{path}", file=sys.stderr)
        return 2

    payload = snapshot(frame)
    payload["image"] = str(path)
    payload["size"] = [int(frame.shape[1]), int(frame.shape[0])]
    text = json.dumps(payload, ensure_ascii=False, indent=args.indent)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - 非 TTY/老 Python
        pass
    print(text)
    return 0 if payload["shop"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


try:
    from .vision import silence_ocr_logs

    silence_ocr_logs()
except Exception:
    pass
