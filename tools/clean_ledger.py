"""清理记录里的坏数据：

1. 商店刷新时间 > 360 秒（把 03:00 读成 30:00 那批）
2. 价格落在档位合法区间之外（把 19 读成 1 那种）

会先备份成 `.bak`。
"""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maplebot import shop  # noqa: E402

PATH = ROOT / "data" / "trade" / "observations.jsonl"
BACKUP = PATH.with_suffix(".jsonl.bak")
MAX_REFRESH = 360


def main():
    if not PATH.exists():
        print("没有记录文件")
        return 1
    goods = shop.load_goods()
    kept, dropped_obs, dropped_rows, total_rows = [], 0, 0, 0
    for line in PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if (row.get("refresh_in") or 0) > MAX_REFRESH:
            dropped_obs += 1
            continue
        rows = row.get("rows") or []
        clean = []
        for item in rows:
            total_rows += 1
            price = item.get("price")
            good = goods.get(item.get("good_id"), {})
            if price is not None and not shop._price_plausible(good, price):
                dropped_rows += 1
                continue
            clean.append(item)
        if rows and not clean:
            dropped_obs += 1
            continue
        row["rows"] = clean
        kept.append(json.dumps(row, ensure_ascii=False))

    shutil.copy2(PATH, BACKUP)
    PATH.write_text("\n".join(kept) + "\n", encoding="utf-8")
    print(f"备份: {BACKUP.name}")
    print(f"删除整条观察 {dropped_obs} 条（刷新时间超限 / 整行都不合法）")
    print(f"删除越界价格 {dropped_rows} / {total_rows} 行")
    print(f"保留观察 {len(kept)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
