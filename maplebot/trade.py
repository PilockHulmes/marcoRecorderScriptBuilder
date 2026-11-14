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

import argparse
import json
import logging
import re
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

# ---------------------------------------------------------------- 几何常量
#: 标定用的窗口尺寸。三张截图都是 1368×800（任务书里的 1382×807 是含边框的
#: 窗口外尺寸，截图画布是客户区）。
BASE_WIDTH = 1368.0
BASE_HEIGHT = 800.0

#: SHOP 窗口**内容区**（不含外框）：x 415..651，y 223..568。
#: 这是 (x, y, w, h)，单位是 @1368×800 的像素；`find_shop_window` 用它判断
#: 标题和图标槽，`read_rows` 用它裁行。
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
COINS_BOX = (788, 234, 52, 20)
WEIGHT_BOX = (775, 254, 65, 22)

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
    sx, sy = _scale(frame)
    x, y, w, h = box
    height, width = frame.shape[:2]
    x0 = max(0, min(width, int(round(x * sx))))
    y0 = max(0, min(height, int(round(y * sy))))
    x1 = max(0, min(width, int(round((x + w) * sx))))
    y1 = max(0, min(height, int(round((y + h) * sy))))
    return x0, y0, x1 - x0, y1 - y0


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
def read_row_countdown(frame) -> str:
    """读「商品/價格變動中止」下面的倒计时，返回 ``"01:18"``；读不到返回空串。"""
    if _empty(frame):
        return ""
    crop = _crop(frame, COUNTDOWN_BOX)
    if crop is None:
        return ""
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


def _read_price(frame, top, dy):
    crop = _crop(frame, (PRICE_BOX[0], top + dy, PRICE_BOX[2], PRICE_BOX[3]))
    if crop is None:
        return None
    value = _first_int(_ocr_text(crop, mode="yellow"))
    if value is not None:
        return value
    return _first_int(_ocr_text(crop, mode="raw"))


def read_rows(frame) -> list[Row]:
    """读商品列表，最多 4 条；SHOP 不在时返回空列表。

    第 4 行通常被视口底边裁掉，这时 ``partial=True``，也读不到价格。
    """
    if _empty(frame) or not find_shop_window(frame):
        return []

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
        name_crop = _crop(frame, (NAME_BOX[0], top + 1, NAME_BOX[2], NAME_BOX[3]))
        name = _ocr_text(name_crop, mode="white", upscale=NAME_UPSCALE,
                         interpolation=cv2.INTER_NEAREST)
        name = name.strip(" \t\r\n【】[]()（）—-_.,，。:：|")

        if partial:
            buy = sell = None
        else:
            buy = _read_price(frame, top, BUY_DY)
            sell = _read_price(frame, top, SELL_DY)
        rows.append(Row(icon_box=icon_box, name_ocr=name,
                        buy_price=buy, sell_price=sell, partial=partial))
    return rows


# ---------------------------------------------------------------- CARGO
def read_cargo(frame) -> Cargo:
    """读 CARGO 顶部的金币 / 当前重量 / 容量。

    图里没有 SHOP/CARGO 或 OCR 读不出来时抛 :class:`TradeParseError`。
    """
    if _empty(frame) or not find_shop_window(frame):
        raise TradeParseError("没有检测到 SHOP 窗口")

    coins_crop = _crop(frame, COINS_BOX)
    weight_crop = _crop(frame, WEIGHT_BOX)
    if coins_crop is None or weight_crop is None:
        raise TradeParseError("CARGO 数字区域超出画面")

    coins = _first_int(_ocr_text(coins_crop, mode="light"))
    weight_text = _ocr_text(weight_crop, mode="light")
    match = re.search(r"(\d+)\s*/\s*(\d+)", weight_text)
    if match is None:
        # 二值化可能把斜杠吃掉；原图再试一次。
        weight_text = _ocr_text(weight_crop, mode="raw")
        match = re.search(r"(\d+)\s*/\s*(\d+)", weight_text)
    if coins is None or match is None:
        raise TradeParseError(f"CARGO 读不出来：coins={coins!r} weight={weight_text!r}")
    return Cargo(coins=coins, weight=int(match.group(1)), capacity=int(match.group(2)))


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
