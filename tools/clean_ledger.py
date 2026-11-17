"""清理记录里的坏数据。

1. 商店刷新时间 > 360 秒（把 03:00 读成 30:00 那批）
2. 价格落在档位合法区间之外（把 19 读成 1 那种）
3. 商人卖的东西和 `goods.json` 里的归属对不上（我自己做性能测试时
   把同一张截图反复喂进真实会话，污染了记录簿）

会先备份成 `.bak`；清完把新格式的 observations.json 删掉，让它重新迁移。
"""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maplebot import shop  # noqa: E402

PATH = ROOT / "data" / "trade" / "observations.jsonl"
STORE = ROOT / "data" / "trade" / "observations.json"
BACKUP = PATH.with_suffix(".jsonl.bak")
MAX_REFRESH = 360


def main():
    if not PATH.exists():
        print("没有记录文件")
        return 1
    goods = shop.load_goods()
    seller_of = {gid: item.get("seller") for gid, item in goods.items()}
    kept, dropped_obs, dropped_rows, total_rows, dropped_seller = [], 0, 0, 0, 0
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

        merchant_id = row.get("merchant_id") or ""
        rows = row.get("rows") or []
        clean, sells_kept, sells_dropped = [], 0, 0
        for item in rows:
            total_rows += 1
            price = item.get("price")
            good = goods.get(item.get("good_id"), {})
            if price is not None and not shop._price_plausible(good, price):
                dropped_rows += 1
                continue
            side = item.get("side")
            if side == "sell" and merchant_id:
                seller = seller_of.get(item.get("good_id"))
                if seller and seller != merchant_id:
                    # 这个商人根本不卖它：整行丢掉
                    sells_dropped += 1
                    continue
            if side == "sell":
                sells_kept += 1
            clean.append(item)

        if sells_dropped and not sells_kept:
            # 全是别人的货：整条记录都是我测试时喂进去的
            dropped_seller += 1
            continue
        if rows and not clean:
            dropped_obs += 1
            continue
        row["rows"] = clean
        kept.append(json.dumps(row, ensure_ascii=False))

    shutil.copy2(PATH, BACKUP)
    PATH.write_text("\n".join(kept) + "\n", encoding="utf-8")
    if STORE.exists():
        STORE.unlink()
        print(f"已删除 {STORE.name}（下次启动会用清理后的记录重新迁移）")
    print(f"备份: {BACKUP.name}")
    print(f"删除整条观察 {dropped_obs} 条（刷新时间超限 / 整行都不合法）")
    print(f"删除商人归属不符的观察 {dropped_seller} 条")
    print(f"删除越界价格 {dropped_rows} / {total_rows} 行")
    print(f"保留观察 {len(kept)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
