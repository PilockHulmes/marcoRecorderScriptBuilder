"""给 goods.json 补上 name_tw（游戏内繁体名），来源合并两张表。"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOODS = ROOT / "data" / "trade" / "goods.json"
NAMES = ROOT / "data" / "trade" / "good_names.json"
EXTRACT = ROOT / "tests" / "tmp_extract_trade_assets.py"

# 逐张截图抄录的繁体名（35 个），优先级最高
text = EXTRACT.read_text(encoding="utf-8")
match = re.search(r"NAME_TO_GOOD\s*=\s*\{(.*?)\n\}", text, re.S)
curated = {}
for key, good_id in re.findall(r'"([^"]+)"\s*:\s*"([^"]+)"', match.group(1)):
    curated.setdefault(good_id, key)


# 今天从真实截图里读到的写法，优先级最高（覆盖之前的推断）
FROM_GAME = {
    "fine_silk": "刺繡的布料",
    "legendary_tonic": "傳說的精神劑",
    "monster_meat": "怪物的肉",
    "refined_black_crystal": "精煉的黑水晶",
    "refined_lithium": "精煉的鋰",
    "top_vitamin": "最高級維他命",
    "wild_ginseng": "百年山蔘",
    "noble_satin": "貴族的布料",
}

# 其余来自名字表（今天补的是游戏里真实读到的写法）
extra = {}
for name, good_id in json.loads(NAMES.read_text(encoding="utf-8")).items():
    extra.setdefault(good_id, name)

payload = json.loads(GOODS.read_text(encoding="utf-8"))
changed = 0
for good in payload["goods"]:
    good_id = good["id"]
    name_tw = (FROM_GAME.get(good_id) or curated.get(good_id)
               or extra.get(good_id) or good["name"])
    if good.get("name_tw") != name_tw:
        good["name_tw"] = name_tw
        changed += 1

GOODS.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"goods.json: {len(payload['goods'])} 个商品，写入 name_tw {changed} 处")
for good in payload["goods"]:
    if good["name_tw"] != good["name"]:
        print(f"  {good['name']:8} -> {good['name_tw']}")
