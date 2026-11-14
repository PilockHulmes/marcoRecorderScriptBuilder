"""从 15 张商人截图里读出每张图的小地图名，生成 商人 -> 地图 表。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from maplebot import mapwatch

SHOTS = ROOT / "screenshots" / "trading" / "trader_ui"
INDEX = ROOT / "data" / "trade" / "merchant_index.json"
OUT = ROOT / "data" / "trade" / "merchant_maps.json"


def read(path):
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


def main():
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    by_file = {}
    for item in index.get("merchants", []):
        src = Path(str(item.get("source", ""))).name
        by_file[src] = item

    result = {}
    for shot in sorted(SHOTS.glob("*.png")):
        frame = read(shot)
        crop = mapwatch.name_crop(frame)
        name = mapwatch._vision_read(crop) if crop is not None else ""
        item = by_file.get(shot.name, {})
        merchant_id = item.get("id", "")
        merchant_name = item.get("name", "")
        result[shot.name] = {"merchant_id": merchant_id, "merchant": merchant_name,
                             "map": name}
        print(f"{shot.name:26} 商人={merchant_name or '?':12} 地图={name!r}")

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", OUT, len(result))


if __name__ == "__main__":
    main()
