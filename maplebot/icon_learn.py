"""商品名 / 商品图标的「在线学习」小工具。

跑商商店窗口里，商品图标靠模板匹配认 good_id；模板只有 35 个，10 个波动货
本轮没上架，所以刚遇到时认不出来。这里做两件很轻的事：

1. **学名字**：图标认出来以后，用视觉读同一行的商品名（繁体），把
   ``名字 -> good_id`` 追加到 ``data/trade/good_names.json``；
2. **学图标**：图标认不出来时，先读名字；名字在表里就把这一格的图标存成
   ``data/trade/icons/<good_id>.png``，下次模板匹配就能认出来。名字也不认识
   就落到 ``data/trade/icons_unknown/<时间戳>.png``，留待人工归类。

设计约束（对应任务书）：

- 所有写入都幂等：同名映射不覆盖，同 good_id 图标已存在就跳过；
- 视觉不可用 / 网络断 / 图片坏了都只返回空串，**绝不向上抛异常**；
- 路径全部可注入，测试用临时目录，不碰真实 ``data/``；
- 学习失败有冷却，避免每 2 秒重试一次视觉接口。
"""

import json
import re
import time
from pathlib import Path

import cv2

from . import trade

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "trade"
GOOD_NAMES_PATH = DATA_DIR / "good_names.json"
ICONS_DIR = DATA_DIR / "icons"
UNKNOWN_DIR = DATA_DIR / "icons_unknown"

#: 商品名裁图只有 17 px 高，放大后视觉才看得清
NAME_UPSCALE = 6
NAME_MAX_CHARS = 12

#: 学习失败后的冷却（秒）。同一商品/同一块图标在此期间不再请求视觉。
FAIL_COOLDOWN_SECONDS = 300.0

VISION_SYSTEM = (
    "你是冒险岛跑商商品名识别器。图片是商店列表里的一行商品名（繁体中文）。"
    "只输出商品名原文，不要引号、不要标点、不要解释；看不清就输出空。"
)
VISION_USER = "只输出商品名。"

_failed_at = {}


# ---------------------------------------------------------------- 冷却
def should_attempt(key, now=None):
    """同一 key 学习失败后冷却一段时间，避免每帧都打视觉接口。"""
    now = time.monotonic() if now is None else float(now)
    last = _failed_at.get(str(key))
    return last is None or now - last >= FAIL_COOLDOWN_SECONDS


def note_failure(key, now=None):
    _failed_at[str(key)] = time.monotonic() if now is None else float(now)


def reset_learning_cache():
    """清空失败冷却（测试用；运行期一般不需要）。"""
    _failed_at.clear()


# ---------------------------------------------------------------- 名字表
def load_good_names(path=None):
    """读 ``名字 -> good_id``；文件坏了/不存在都返回空 dict。"""
    path = Path(path) if path is not None else GOOD_NAMES_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    names = {}
    for key, value in data.items():
        name = str(key).strip()
        good_id = str(value).strip()
        if name and good_id:
            names[name] = good_id
    return names


def save_good_names(mapping, path=None):
    """整表写回（按名字排序）；失败返回 False，不抛异常。"""
    path = Path(path) if path is not None else GOOD_NAMES_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {str(k): str(v) for k, v in sorted(mapping.items()) if k and v}
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)
        return True
    except Exception:
        return False


def valid_name(name):
    """商品名至少含一个汉字且不超过 12 字，挡掉 "Unknown" 这类垃圾。"""
    name = str(name or "").strip()
    if not name or len(name) > NAME_MAX_CHARS:
        return False
    return any("\u4e00" <= ch <= "\u9fff" for ch in name)


def record_good_name(name, good_id, path=None, mapping=None):
    """把 ``name -> good_id`` 记进表；已存在/无效返回 False（不覆盖）。"""
    name = str(name or "").strip()
    good_id = str(good_id or "").strip()
    if not valid_name(name) or not good_id:
        return False
    names = mapping if mapping is not None else load_good_names(path)
    if name in names:
        return False
    names[name] = good_id
    return save_good_names(names, path)


def has_name_for(good_id, mapping):
    """这个 good_id 是否已经有至少一个名字（用于避免重复调视觉）。"""
    good_id = str(good_id or "")
    return any(value == good_id for value in mapping.values())


# ---------------------------------------------------------------- 名字识别
def clean_goods_name(text):
    """清掉视觉模型爱加的引号、冒号、括号注释，只留商品名。"""
    if not text:
        return ""
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    if not lines:
        return ""
    line = lines[0]
    for sep in (":", "："):
        if sep in line:
            line = line.rsplit(sep, 1)[-1]
    line = re.sub(r"[（(【\[].*?[）)】\]]", "", line)
    line = line.strip(" \t\r\n\"'“”‘’「」『』【】[]()（）<>《》.,，。!！?？;；:：、")
    line = line.strip()
    if not line or len(line) > NAME_MAX_CHARS:
        return ""
    if not any("\u4e00" <= ch <= "\u9fff" for ch in line):
        return ""
    return line


def _default_vision(crop):
    from .vision import VisionClient

    return VisionClient(timeout=15.0).ask(
        crop, system=VISION_SYSTEM, user=VISION_USER, max_tokens=24,
    )


def read_goods_name(crop, vision=None):
    """视觉读一小块商品名图；任何失败都安静返回空串。

    :param vision: 可注入的 ``ndarray -> str``；测试用它替代网络调用。
    """
    if crop is None or getattr(crop, "size", 0) == 0:
        return ""
    try:
        height = max(1, int(crop.shape[0]))
        scale = max(1, min(NAME_UPSCALE, int(round(120 / height))))
        big = cv2.resize(crop, None, fx=scale, fy=scale,
                         interpolation=cv2.INTER_NEAREST)
        big = cv2.copyMakeBorder(big, 16, 16, 16, 16, cv2.BORDER_REPLICATE)
    except Exception:
        return ""
    try:
        text = vision(big) if vision is not None else _default_vision(big)
    except Exception:
        return ""
    return clean_goods_name(text)


def row_name_box(icon_box):
    """由图标槽 ``(x, y, w, h)`` 推出同一行的商品名裁图框。

    常量都在 :mod:`maplebot.trade` 里，按图标槽缩放比例换算，字号变化也能用。
    """
    x, y, w, h = (int(v) for v in icon_box)
    if w <= 0 or h <= 0:
        return None
    sx = w / float(trade.ICON_BOX[2])
    sy = h / float(trade.ICON_BOX[3])
    nx = x + int(round((trade.NAME_BOX[0] - trade.ICON_BOX[0]) * sx))
    ny = y + int(round((trade.NAME_BOX[1] - trade.ICON_BOX[1] + 1) * sy))
    nw = max(1, int(round(trade.NAME_BOX[2] * sx)))
    nh = max(1, int(round(trade.NAME_BOX[3] * sy)))
    return nx, ny, nw, nh


def read_row_name(frame, icon_box, vision=None):
    """从整帧里裁出这一行的名字并识别；裁不到/读不出返回空串。"""
    if frame is None or getattr(frame, "size", 0) == 0 or icon_box is None:
        return ""
    try:
        box = row_name_box(icon_box)
        if box is None:
            return ""
        nx, ny, nw, nh = box
        height, width = frame.shape[:2]
        x0, y0 = max(0, nx), max(0, ny)
        x1, y1 = min(width, nx + nw), min(height, ny + nh)
        if x1 <= x0 or y1 <= y0:
            return ""
        return read_goods_name(frame[y0:y1, x0:x1], vision=vision)
    except Exception:
        return ""


# ---------------------------------------------------------------- 图标落盘
def _safe_good_id(good_id):
    good_id = str(good_id or "").strip()
    if not good_id or any(ch in good_id for ch in '/\\:*?"<>|'):
        return ""
    return good_id


def save_icon(good_id, crop, icon_dir=None):
    """把图标存成 ``<good_id>.png``；已存在/写失败返回 None，不覆盖。"""
    good_id = _safe_good_id(good_id)
    if not good_id or crop is None or getattr(crop, "size", 0) == 0:
        return None
    path = (Path(icon_dir) if icon_dir is not None else ICONS_DIR) / f"{good_id}.png"
    if path.exists():
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ok, buffer = cv2.imencode(".png", crop)
        if not ok:
            return None
        buffer.tofile(str(path))
        return path
    except Exception:
        return None


def save_unknown_icon(crop, unknown_dir=None, stamp=None):
    """存一块认不出的图标，文件名用时间戳；返回路径或 None。"""
    if crop is None or getattr(crop, "size", 0) == 0:
        return None
    folder = Path(unknown_dir) if unknown_dir is not None else UNKNOWN_DIR
    try:
        folder.mkdir(parents=True, exist_ok=True)
        tag = stamp or time.strftime("%Y%m%d_%H%M%S", time.localtime())
        suffix = ""
        path = folder / f"{tag}{suffix}.png"
        while path.exists():
            suffix = "_1" if not suffix else f"_{int(suffix[1:]) + 1}"
            path = folder / f"{tag}{suffix}.png"
        ok, buffer = cv2.imencode(".png", crop)
        if not ok:
            return None
        buffer.tofile(str(path))
        return path
    except Exception:
        return None
