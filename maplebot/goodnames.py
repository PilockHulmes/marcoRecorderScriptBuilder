"""商品名解析：繁简、别名、OCR 形近字。

为什么需要：游戏是繁体，OCR 有时把繁体认成形近的简体（例如 貴 → 贵），
直接拿字符串查"名字 → good_id"表就查不到，整行商品会被丢掉。

解析顺序（越往后越宽松）：

1. 精确匹配名字表
2. 繁简归一后再匹配（:data:`SIMP_TRAD`）
3. 用 ``goods.json`` 里的 ``name`` / ``name_tw`` 归一后匹配
4. 同长度、字符重合度 ≥ ``FUZZY_RATIO`` 的模糊匹配（兜 OCR 形近字）
"""

from __future__ import annotations

#: 形近/繁简对照：OCR 常把繁体认成这些简体字，统一折成繁体
SIMP_TRAD = {
    "贵": "貴", "猪": "豬", "钻": "鑽", "矿": "礦", "链": "鏈", "丝": "絲",
    "绸": "綢", "缎": "緞", "绣": "繡", "毡": "氈", "钢": "鋼", "铁": "鐵",
    "闪": "閃", "亮": "亮", "钻": "鑽", "宝": "寶", "贝": "貝", "财": "財",
    "猫": "貓", "猪": "豬", "驴": "驢", "鲜": "鮮", "鱼": "魚", "鸟": "鳥",
    "龙": "龍", "龟": "龜", "伞": "傘", "药": "藥", "补": "補", "剂": "劑",
    "传": "傳", "说": "說", "灵": "靈", "兽": "獸", "猎": "獵", "围": "圍",
    "红": "紅", "绿": "綠", "蓝": "藍", "黄": "黃", "褐": "褐", "绒": "絨",
    "绵": "綿", "纱": "紗", "绢": "絹", "织": "織", "编": "編", "纤": "纖",
    "维": "維", "铜": "銅", "银": "銀", "铅": "鉛", "锌": "鋅", "锡": "錫",
    "钱": "錢", "铁": "鐵", "质": "質", "贝": "貝", "页": "頁", "风": "風",
    "马": "馬", "鸟": "鳥", "鲁": "魯", "鲁": "魯", "鸡": "雞", "鸭": "鴨",
    "鹅": "鵝", "鲜": "鮮", "鲤": "鯉", "鲨": "鯊", "鳄": "鱷", "虾": "蝦",
    "龟": "龜", "壳": "殼", "壶": "壺", "坛": "罈", "罐": "罐", "盐": "鹽",
    "酱": "醬", "酿": "釀", "饼": "餅", "糕": "糕", "糖": "糖", "粮": "糧",
    "种": "種", "积": "積", "称": "稱", "稳": "穩", "贸": "貿", "货": "貨",
    "贩": "販", "购": "購", "买": "買", "卖": "賣", "价": "價", "储": "儲",
    "备": "備", "条": "條", "约": "約", "级": "級", "纯": "純", "细": "細",
    "织": "織", "经": "經", "济": "濟", "统": "統", "结": "結", "给": "給",
    "络": "絡", "续": "續", "缘": "緣", "缩": "縮", "缝": "縫", "缠": "纏",
}

#: 同长度时允许多少字符不同（模糊匹配的门槛）
FUZZY_RATIO = 0.7


def fold(name):
    """把名字里的简体/形近字折成繁体，便于比较。"""
    if not name:
        return ""
    return "".join(SIMP_TRAD.get(ch, ch) for ch in str(name))


def _goods_names(goods):
    """``{归一后的名字: good_id}``，来自 goods.json 的 name / name_tw。"""
    table = {}
    for good_id, item in (goods or {}).items():
        if not isinstance(item, dict):
            continue
        for key in (item.get("name_tw"), item.get("name")):
            if key:
                table.setdefault(fold(key), good_id)
    return table


def _fuzzy(name, mapping):
    """同长度、字符重合度够高的唯一候选。"""
    target = fold(name)
    if not target:
        return ""
    best, best_ratio, tie = "", 0.0, False
    for key, good_id in mapping.items():
        if len(key) != len(target):
            continue
        same = sum(1 for a, b in zip(key, target) if a == b)
        ratio = same / len(target)
        if ratio < FUZZY_RATIO:
            continue
        if ratio > best_ratio:
            best, best_ratio, tie = good_id, ratio, False
        elif ratio == best_ratio and good_id != best:
            tie = True
    return "" if tie else best


def resolve(name, names=None, goods=None):
    """把 OCR 出来的商品名解析成 ``good_id``；解析不出返回 ``""``。"""
    if not name:
        return ""
    name = str(name).strip()
    if not name:
        return ""
    names = names or {}
    exact = names.get(name)
    if exact:
        return exact

    folded = fold(name)
    if folded == name:
        pass
    # 名字表也按归一后的形式比较一次
    folded_names = {}
    for key, good_id in names.items():
        folded_names.setdefault(fold(key), good_id)
    hit = folded_names.get(folded)
    if hit:
        return hit

    goods_table = _goods_names(goods)
    hit = goods_table.get(folded)
    if hit:
        return hit

    # 模糊匹配：先在名字表里找，再在商品表里找
    hit = _fuzzy(name, folded_names)
    if hit:
        return hit
    return _fuzzy(name, goods_table)
