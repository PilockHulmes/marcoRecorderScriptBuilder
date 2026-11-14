"""观察记录簿：把每次打开商店的结果存下来，并回答"这个价还有效吗"。

有效期模型（TRADE_DESIGN.md 13.5）：

    valid_until = 观察时刻 + 该 NPC 的刷新倒计时

给建议前要查两道：现在没过期、跑到时也没过期。
"""

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "data" / "trade" / "observations.jsonl"


class Ledger:
    def __init__(self, path=None):
        self.path = Path(path or DEFAULT_PATH)

    # ---------------------------------------------------------------- 写
    def record(self, visit, now=None):
        """存一条观察；visit 是 shop.Visit 或它的 to_dict()。"""
        payload = visit.to_dict() if hasattr(visit, "to_dict") else dict(visit)
        payload["t"] = float(now if now is not None else time.time())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return payload

    # ---------------------------------------------------------------- 读
    def load(self):
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out

    # ------------------------------------------------------------ 有效期
    @staticmethod
    def valid_until(observation):
        return float(observation.get("t", 0)) + float(observation.get("refresh_in", 0))

    def valid(self, at=None):
        """在这一时刻仍然有效的观察。"""
        moment = float(at if at is not None else time.time())
        return [o for o in self.load() if self.valid_until(o) > moment]

    # -------------------------------------------------------------- 查询
    def best_bid(self, good_id, at=None, exclude_map=None):
        """`at` 时刻仍然有效、对这件货出价最高的收购记录。"""
        moment = float(at if at is not None else time.time())
        best = None
        for observation in self.load():
            if self.valid_until(observation) <= moment:
                continue
            if exclude_map and observation.get("map") == exclude_map:
                continue
            for row in observation.get("rows", []):
                if row.get("good_id") != good_id or row.get("side") != "buy":
                    continue
                price = int(row.get("price", 0))
                if price <= 0:
                    continue
                if best is None or price > best["price"]:
                    best = {"price": price, "map": observation.get("map", ""),
                            "merchant": observation.get("merchant", ""),
                            "merchant_id": observation.get("merchant_id", ""),
                            "valid_until": self.valid_until(observation),
                            "observed_at": observation.get("t", 0)}
        return best

    def offers(self, at=None):
        """所有仍然有效的"他卖给我"的记录（用于判断值不值得买）。"""
        moment = float(at if at is not None else time.time())
        out = []
        for observation in self.load():
            if self.valid_until(observation) <= moment:
                continue
            for row in observation.get("rows", []):
                if row.get("side") != "sell":
                    continue
                out.append({"good_id": row.get("good_id"), "good": row.get("good", ""),
                            "price": int(row.get("price", 0)),
                            "map": observation.get("map", ""),
                            "merchant": observation.get("merchant", ""),
                            "valid_until": self.valid_until(observation)})
        return out


def max_units(price, coins, weight, capacity):
    """买得起且装得下的件数（每件重量都是 1）。"""
    if price <= 0:
        return 0
    room = max(0, int(capacity) - int(weight))
    afford = int(coins) // int(price)
    return max(0, min(room, afford))
