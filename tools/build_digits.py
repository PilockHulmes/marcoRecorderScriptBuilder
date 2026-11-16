"""从已知数字的截图里抠出两套数字模板，写入 data/trade/digits.json。

两套字体（实测）：
- fat（粗体，高 10px）：倒计时、金币、负重、货舱数量
- thin（细体，高 8px）：商品价格、聊天输入框

每个样本都写明"这段区域里应该是什么数字"，脚本按顺序把字形和数字对上。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from maplebot import trade  # noqa: E402

OUT = ROOT / "data" / "trade" / "digits.json"
BASE = Path(r"C:\Users\PilockHulmes\.dsh\attachments\v1\objects")
SHOT_A = BASE / "d3" / "d355e69319db84a19d3317e991400ce2fa940d09d104d0312f33b4c9acf8b61a"
SHOT_B = BASE / "b1" / "b17b04a6facc9efee984544e806a8c42c7af8cbfa1f0a729939b10b8ec222fc4"
CHAT = BASE / "89" / "89166728de3c57300e70b8e78b9e93561d456699f81ab6db9e5930d6781d2b3f"


def load(path):
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


def downscale(frame):
    return cv2.resize(frame, (1366, 768), interpolation=cv2.INTER_AREA)


def gold_mask(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, (12, 90, 150), (40, 255, 255))


def white_mask(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return (gray > 150).astype(np.uint8) * 255


def split_glyphs(mask, lo=3, hi=14, min_h=6, max_h=None):
    """按列切字形，返回 [(位图, (x0,x1))]。"""
    cols = (mask > 0).any(axis=0)
    runs, start = [], None
    for i, v in enumerate(cols):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(cols) - 1))
    out = []
    for a, b in runs:
        if not (lo <= b - a + 1 <= hi):
            continue
        sub = mask[:, a:b + 1]
        rows = np.where((sub > 0).any(axis=1))[0]
        if not len(rows) or rows.max() - rows.min() + 1 < min_h:
            continue
        height = rows.max() - rows.min() + 1
        if max_h is not None and height > max_h:
            continue                     # 斜杠、粘连块：不是单个数字
        out.append((sub[rows.min():rows.max() + 1], (a, b)))
    return out


def assign(glyphs, expected):
    """把字形按顺序和期望字符串里的数字对齐（跳过 "/" ":" 等分隔符）。"""
    digits = [ch for ch in expected if ch.isdigit()]
    if len(digits) != len(glyphs):
        return None
    return list(zip(digits, glyphs))


def add(samples, family, glyph, digit):
    height, width = glyph.shape
    key = (height, width)
    table = samples.setdefault(family, {}).setdefault(digit, {})
    table.setdefault(str(key), []).append(glyph)


def main():
    samples = {}
    report = []

    fixture = load(ROOT / "tests" / "fixtures" / "shop_frame.png")
    a = downscale(load(SHOT_A)) if SHOT_A.exists() else None
    b = downscale(load(SHOT_B)) if SHOT_B.exists() else None
    chat = load(CHAT) if CHAT.exists() else None

    jobs = [
        ("fat", fixture, trade.COUNTDOWN_BOX, "03:48", "gold", "fixture 倒计时"),
        ("fat", fixture, trade.CARGO_COINS_SHOP, "0", "gold", "fixture 金币"),
        ("fat", fixture, trade.CARGO_WEIGHT_SHOP, "5/135", "gold", "fixture 负重"),
    ]
    if a is not None:
        jobs.append(("fat", a, trade.COUNTDOWN_BOX, "31:07", "gold", "1920A 倒计时"))
        jobs.append(("fat", a, trade.CARGO_COINS_SHOP, "50", "gold", "1920A 金币"))
    if b is not None:
        jobs.append(("fat", b, trade.COUNTDOWN_BOX, "23:50", "gold", "1920B 倒计时"))
        jobs.append(("thin", b, (trade.PRICE_BOX[0], trade.ROW_TOPS[0] + trade.BUY_DY,
                                 trade.PRICE_BOX[2], trade.PRICE_BOX[3]), "17", "gold", "1920B 价格1"))
        jobs.append(("thin", b, (trade.PRICE_BOX[0], trade.ROW_TOPS[1] + trade.BUY_DY,
                                 trade.PRICE_BOX[2], trade.PRICE_BOX[3]), "60", "gold", "1920B 价格2"))
        jobs.append(("thin", b, (trade.PRICE_BOX[0], trade.ROW_TOPS[2] + trade.SELL_DY,
                                 trade.PRICE_BOX[2], trade.PRICE_BOX[3]), "18", "gold", "1920B 价格3"))
    if chat is not None:
        jobs.append(("thin", chat, (1440, 778, 180, 22), "1234567890", "white", "聊天输入框"))
    six_shot = BASE / "ec" / "ec5c3323ab138e26c8687b7c072060930a45d35492e739e337fcea07acd00b4b"
    if six_shot.exists():
        frame6 = load(six_shot)
        jobs.append(("fat", frame6, trade.COUNTDOWN_BOX, "03:16", "gold", "带6的倒计时"))
        jobs.append(("whitefat", frame6, trade.CARGO_WEIGHT_SHOP, "0/135", "white", "负重 0/135"))
    only_box = BASE / "12" / "1268012dbe814704e6ca0447d40dee5250054c6013d6841125dcacecf8cfa52c"
    if only_box.exists():
        jobs.append(("fat", load(only_box), trade.CARGO_COINS_ONLY, "7923", "gold", "单独货舱 7923"))

    for family, frame, box, expected, mask_kind, label in jobs:
        x, y, w, h = box
        if family == "thin" and frame.shape[1] != 1366 and label != "聊天输入框":
            frame = frame                      # 价格框用的是 1366 坐标，已在 downscale 后
        if label == "聊天输入框":
            crop = frame[y:y + h, x:x + w]        # 截图坐标，不是游戏窗口坐标
        else:
            crop = trade._crop(frame, box)        # 常量是窗口坐标，必须走 _crop
        if crop is None or crop.size == 0:
            report.append((label, "取不到区域"))
            continue
        # 先用 OCR 核对这段区域真的是这个数字，避免标签错位把模板污染了
        check_text = ""
        try:
            check_text = trade._ocr_text(crop, mode="light") or ""
        except Exception:
            check_text = ""
        check_digits = "".join(ch for ch in check_text if ch.isdigit())
        want_digits = "".join(ch for ch in expected if ch.isdigit())
        if check_digits and check_digits != want_digits:
            report.append((label, f"跳过：OCR 读到 {check_digits}，与期望 {want_digits} 不符"))
            continue

        mask = gold_mask(crop) if mask_kind == "gold" else white_mask(crop)
        glyphs = [(g, pos) for g, pos in split_glyphs(mask, max_h=11)]
        pairs = assign(glyphs, expected)
        if pairs is None:
            report.append((label, f"字形数 {len(glyphs)} != 期望位数 {sum(c.isdigit() for c in expected)}"))
            continue
        for digit, (glyph, _pos) in pairs:
            add(samples, family, glyph, digit)
        report.append((label, f"ok {len(pairs)} 位"))

    for label, status in report:
        print(f"  {label}: {status}")

    payload = {}
    for family, digits in samples.items():
        payload[family] = {}
        for digit, sizes in digits.items():
            payload[family][digit] = {k: [g.tolist() for g in v] for k, v in sizes.items()}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    print(f"\n写入 {OUT}")
    for family in sorted(payload):
        have = sorted(payload[family])
        sizes = sorted({k for d in payload[family].values() for k in d})
        print(f"  {family}: 数字 {''.join(have)}  尺寸 {sizes}")
        missing = [str(d) for d in range(10) if str(d) not in payload[family]]
        if missing:
            print(f"    缺: {''.join(missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
