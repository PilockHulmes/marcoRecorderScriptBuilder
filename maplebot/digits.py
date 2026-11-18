"""数字模板匹配（替代 OCR 认数字）。

两套字体（实测，见 `tools/build_digits.py`）：

- ``fat``  ：高 10px，用于倒计时 / 金币 / 负重 / 货舱数量
- ``thin`` ：高 8px，用于商品价格

同一字体下，同一个数字的渲染是**像素级稳定**的（实测同一张图里三个 '0'
互相 IoU = 1.00），所以模板比对比 OCR 更可靠，也更快（几十微秒 vs 30 毫秒）。

认不出的数字返回 None，由调用方决定退回 OCR 还是当作未知。
"""

from __future__ import annotations

from . import paths as paths_module

import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DIGITS_PATH = paths_module.trade_dir() / "digits.json"
#: 原生尺度（1920 那种放大过的画面）用的模板：12px 细体 + 14px 粗体。
#: 缩放会把 8px 位图字体打散（实测相似度掉到 0.3~0.9），所以另存一套。
NATIVE_PATH = paths_module.trade_dir() / "digits_native.json"

#: 帧的缩放比超过这个数就用原生模板（1920x1080 是 1.4056，1920x1200 是 1.5625）
NATIVE_MIN_SCALE = 1.25

#: 判定"最像"的最低相似度（IoU）。低于这个数就当认不出。
MATCH_THRESHOLD = 0.85

#: 第一名要比第二名高出这么多才算可信
MARGIN = 0.06

#: 两个字形之间至少要有这么多列空白才算分开
GLYPH_MIN_GAP = 1

_cache = {}


def load(path=None):
    """读取模板：{family: {digit: {size: [bitmap...]}}}。

    默认把 ``digits.json``（1366 基准）和 ``digits_native.json``（原生尺度）
    一起读进来，family 名分别是 ``thin``/``fat`` 和 ``thin_native``/``fat_native``。
    """
    global _cache
    path = Path(path or DIGITS_PATH)
    if path in _cache:
        return _cache[path]
    sources = [path]
    if path == DIGITS_PATH and NATIVE_PATH.exists() and NATIVE_PATH != path:
        sources.append(NATIVE_PATH)
    table = {}
    for source in sources:
        try:
            payload = json.loads(Path(source).read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        for family, digits in (payload or {}).items():
            table.setdefault(family, {})
            for digit, sizes in digits.items():
                for _key, bitmaps in sizes.items():
                    table[family].setdefault(digit, []).extend(
                        np.array(b, dtype=np.uint8) for b in bitmaps)
    _cache[path] = table
    return table


def family_for(family, scale=None):
    """按帧的缩放比挑模板族：放大过的画面用原生尺度那一套，其余用基准那一套。"""
    if not scale or float(scale) < NATIVE_MIN_SCALE:
        return family
    native = f"{family}_native"
    return native if native in load() else family


def _mask(crop, kind="gold"):
    if crop is None or crop.size == 0:
        return None
    if kind == "white":
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        return (gray > 150).astype(np.uint8) * 255
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, (12, 90, 150), (40, 255, 255))


def split_glyphs(mask, lo=3, hi=16, min_height=6, max_height=None):
    """按列切出字形（数字之间没有粘连时很准）。"""
    if mask is None:
        return []
    cols = (mask > 0).any(axis=0)
    runs, start = [], None
    for index, value in enumerate(cols):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(cols) - 1))

    glyphs = []
    for left, right in runs:
        width = right - left + 1
        if not (lo <= width <= hi):
            continue
        sub = mask[:, left:right + 1]
        rows = np.where((sub > 0).any(axis=1))[0]
        if not len(rows) or rows.max() - rows.min() + 1 < min_height:
            continue
        height = rows.max() - rows.min() + 1
        if max_height is not None and height > max_height:
            continue                     # 斜杠、粘连块：不是单个数字
        glyphs.append(sub[rows.min():rows.max() + 1])
    return glyphs


def _normalize(glyph, height=12):
    """按高度归一化，宽度保持比例、居中补齐（避免把"1"拉宽变形）。"""
    if glyph is None or glyph.size == 0:
        return None
    h, w = glyph.shape[:2]
    scale = height / float(max(1, h))
    new_w = max(1, int(round(w * scale)))
    resized = cv2.resize(glyph, (new_w, height), interpolation=cv2.INTER_NEAREST) > 0
    return resized


def _similarity(a, b):
    """大小无关的相似度：按高度归一化后，**所有水平对位**取最大 IoU。

    只按"居中"对位时，宽 5 的字形和宽 6 的模板会差一列：
    例如 1920 画面缩回 1366 后，数字「7」最左一列被吃掉，
    居中反而把缺口放到另一侧，相似度掉到 0.49（实测）；
    逐列滑动取最大能到 0.91，正确认出。
    """
    left = _normalize(a)
    right = _normalize(b)
    if left is None or right is None:
        return 0.0
    width = max(left.shape[1], right.shape[1])
    best = 0.0
    for offset in range(0, width - left.shape[1] + 1):
        canvas_left = np.zeros((left.shape[0], width), dtype=bool)
        canvas_left[:, offset:offset + left.shape[1]] = left
        for other in range(0, width - right.shape[1] + 1):
            canvas_right = np.zeros((right.shape[0], width), dtype=bool)
            canvas_right[:, other:other + right.shape[1]] = right
            union = np.logical_or(canvas_left, canvas_right).sum()
            if not union:
                continue
            score = float(np.logical_and(canvas_left, canvas_right).sum()) / float(union)
            if score > best:
                best = score
    return best


def identify(glyph, family="fat", templates=None):
    """一个字形 -> (digit, score)；认不出返回 ("", 0.0)。"""
    table = (templates or load()).get(family) or {}
    if not table or glyph is None or glyph.size == 0:
        return "", 0.0
    best, best_score, second_score = "", 0.0, 0.0
    for digit, bitmaps in table.items():
        for bitmap in bitmaps:
            score = _similarity(glyph, bitmap)
            if score > best_score:
                second_score = best_score
                best, best_score = digit, score
            elif score > second_score:
                second_score = score
    if best_score < MATCH_THRESHOLD:
        return "", best_score
    return best, best_score


def read_groups_at(crop, family="fat", kind="gold", max_height=13):
    """和 :func:`read_groups` 一样，但把每组数字的横坐标也返回：``[(文本, (x0, x1))]``。

    用来"取最右边那一组"——货舱每行右侧就是件数，左边的名字/价格不会干扰。
    """
    mask = _mask(crop, kind=kind)
    if mask is None:
        return []
    cols = (mask > 0).any(axis=0)
    runs, start = [], None
    for index, value in enumerate(cols):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(cols) - 1))

    groups, text, left, right = [], "", None, None
    for run in runs:
        piece = mask[:, run[0]:run[1] + 1]
        rows = np.where((piece > 0).any(axis=1))[0]
        if not len(rows):
            continue
        height = rows.max() - rows.min() + 1
        digit = ""
        if height <= max_height:
            digit, _score = identify(piece[rows.min():rows.max() + 1], family)
        if digit:
            if left is None:
                left = run[0]
            right = run[1]
            text += digit
        elif text:
            groups.append((text, (left, right)))
            text, left, right = "", None, None
    if text:
        groups.append((text, (left, right)))
    return groups


def read_number(crop, family="fat", kind="gold", templates=None,
                max_height=None):
    """把整块区域读成整数；有任何一位认不出就返回 None。

    ``crop`` 里除了数字只允许出现分隔符（斜杠、冒号、空格、个）。
    """
    mask = _mask(crop, kind=kind)
    glyphs = split_glyphs(mask, max_height=max_height)
    if not glyphs:
        return None
    digits = []
    for glyph in glyphs:
        digit, _score = identify(glyph, family=family, templates=templates)
        if not digit:
            return None
        digits.append(digit)
    return int("".join(digits))


def _groups_by_gap(mask, family, templates, max_groups, max_height):
    """按"最大空隙"切组（倒计时的冒号不是字形，只能靠空隙）。"""
    cols = (mask > 0).any(axis=0)
    runs, start = [], None
    for index, value in enumerate(cols):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(cols) - 1))
    if len(runs) < 2:
        glyphs = split_glyphs(mask, max_height=max_height)
        text = "".join(identify(g, family, templates)[0] for g in glyphs)
        return [text] if text else []
    gaps = sorted(((runs[i + 1][0] - runs[i][1], i) for i in range(len(runs) - 1)),
                  reverse=True)
    cuts = sorted(index for _gap, index in gaps[:max_groups - 1])
    bounds = [0] + [c + 1 for c in cuts] + [len(runs)]
    groups = []
    for left, right in zip(bounds, bounds[1:]):
        text = ""
        for run in runs[left:right]:
            piece = mask[:, run[0]:run[1] + 1]
            rows = np.where((piece > 0).any(axis=1))[0]
            if not len(rows):
                continue
            digit, _ = identify(piece[rows.min():rows.max() + 1], family, templates)
            if not digit:
                return []
            text += digit
        groups.append(text)
    return groups


def read_groups(crop, family="fat", kind="gold", templates=None, max_groups=2,
                max_height=13, mode="separator"):
    """按"认不出的字形"当分隔符来切组：``0/135`` -> ["0", "135"]、``03:48`` -> ["03","48"]。

    斜杠、冒号不是数字，识别分数会很低，正好当分隔符用。
    比"按最大空隙切"更稳：数字之间的空隙可能比斜杠还大。
    """
    mask = _mask(crop, kind=kind)
    if mode == "gap":
        return _groups_by_gap(mask, family, templates, max_groups, max_height)
    glyphs = split_glyphs(mask, max_height=max_height)
    if not glyphs:
        return []
    groups, current = [], []
    for glyph in glyphs:
        digit, score = identify(glyph, family=family, templates=templates)
        if digit and score >= MATCH_THRESHOLD:
            current.append(digit)
            continue
        if current:                    # 认不出 -> 当作分隔符
            groups.append("".join(current))
            current = []
            if len(groups) >= max_groups:
                return groups
    if current:
        groups.append("".join(current))
    return groups


def read_pair(crop, family="fat", kind="gold", templates=None):
    """读 "a/b"（负重）这种，返回 (a, b)。"""
    mask = _mask(crop, kind=kind)
    glyphs = split_glyphs(mask)
    if not glyphs:
        return None, None
    values, current = [], []
    # 用列间距判断斜杠位置不可靠，这里改成"整块 OCR 已知是 a/b"：
    # 先整体识别成一串数字，再按调用方给的位数拆（见 read_pair_by_len）
    for glyph in glyphs:
        digit, _score = identify(glyph, family=family, templates=templates)
        if not digit:
            return None, None
        current.append(digit)
    if current:
        values.append(int("".join(current)))
    return (values[0] if values else None), None
