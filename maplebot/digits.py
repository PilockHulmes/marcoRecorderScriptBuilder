"""数字模板匹配（替代 OCR 认数字）。

两套字体（实测，见 `tools/build_digits.py`）：

- ``fat``  ：高 10px，用于倒计时 / 金币 / 负重 / 货舱数量
- ``thin`` ：高 8px，用于商品价格

同一字体下，同一个数字的渲染是**像素级稳定**的（实测同一张图里三个 '0'
互相 IoU = 1.00），所以模板比对比 OCR 更可靠，也更快（几十微秒 vs 30 毫秒）。

认不出的数字返回 None，由调用方决定退回 OCR 还是当作未知。
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DIGITS_PATH = ROOT / "data" / "trade" / "digits.json"

#: 判定"最像"的最低相似度（IoU）。低于这个数就当认不出。
MATCH_THRESHOLD = 0.62

#: 两个字形之间至少要有这么多列空白才算分开
GLYPH_MIN_GAP = 1

_cache = {}


def load(path=None):
    """读取模板：{family: {digit: {size: [bitmap...]}}}。"""
    global _cache
    path = Path(path or DIGITS_PATH)
    if path in _cache:
        return _cache[path]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    table = {}
    for family, digits in (payload or {}).items():
        table[family] = {}
        for digit, sizes in digits.items():
            for key, bitmaps in sizes.items():
                table[family].setdefault(digit, []).extend(
                    np.array(b, dtype=np.uint8) for b in bitmaps)
    _cache[path] = table
    return table


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
    """大小无关的相似度：都按高度归一化后居中排布，比 IoU。"""
    left = _normalize(a)
    right = _normalize(b)
    if left is None or right is None:
        return 0.0
    width = max(left.shape[1], right.shape[1])
    def pad(img):
        canvas = np.zeros((img.shape[0], width), dtype=bool)
        offset = (width - img.shape[1]) // 2
        canvas[:, offset:offset + img.shape[1]] = img
        return canvas
    left, right = pad(left), pad(right)
    union = np.logical_or(left, right).sum()
    if not union:
        return 0.0
    return float(np.logical_and(left, right).sum()) / float(union)


def identify(glyph, family="fat", templates=None):
    """一个字形 -> (digit, score)；认不出返回 ("", 0.0)。"""
    table = (templates or load()).get(family) or {}
    if not table or glyph is None or glyph.size == 0:
        return "", 0.0
    best, best_score = "", 0.0
    for digit, bitmaps in table.items():
        for bitmap in bitmaps:
            score = _similarity(glyph, bitmap)
            if score > best_score:
                best, best_score = digit, score
    if best_score < MATCH_THRESHOLD:
        return "", best_score
    return best, best_score


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


def read_groups(crop, family="fat", kind="gold", templates=None, max_groups=2,
                max_height=None):
    """按"最大空隙"把数字分成几组：``0/135`` -> ["0","135"]，``03:48`` -> ["03","48"]。

    斜杠和冒号都不是金色，所以它们的位置就是字形之间最大的空隙。
    """
    mask = _mask(crop, kind=kind)
    glyphs = split_glyphs(mask, max_height=max_height)
    if not glyphs:
        return []
    # 找到每个字形在原图里的列位置，用间距切组
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
    runs = [r for r in runs if 3 <= r[1] - r[0] + 1 <= 16]
    if len(runs) <= 1:
        digits = "".join(identify(g, family, templates)[0] for g in glyphs)
        return [digits] if digits and len(digits) == len(glyphs) else []
    gaps = [(runs[i + 1][0] - runs[i][1], i) for i in range(len(runs) - 1)]
    groups, cuts = [], []
    gaps.sort(reverse=True)
    for _gap, index in gaps[:max_groups - 1]:
        cuts.append(index)
    cuts.sort()
    bounds = [0] + [c + 1 for c in cuts] + [len(runs)]
    for left, right in zip(bounds, bounds[1:]):
        chunk = runs[left:right]
        text = ""
        for run in chunk:
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
