"""观察记录簿：把每次打开商店的结果存下来，并回答"这个价还有效吗"。

有效期模型（TRADE_DESIGN.md 13.5）：

    valid_until = 观察时刻 + 该 NPC 的刷新倒计时

给建议前要查两道：现在没过期、跑到时也没过期。

存储（2026-11-17 改）
--------------------
以前是"每读一次商店追加一行 JSONL"，一小时能攒上万行，每次 load() 都要把
整个文件重新解析（实测每帧 222 ms）。现在改成：

- **内存里**是一张 ``商人 -> 货架周期 -> 货物行`` 的表，读写都是 dict 操作；
- **磁盘上**是 ``observations.json``，只保留每个商人当前的货架；
- 写盘交给后台线程每 5 秒一次（原子替换 + 单个 .bak），主线程不阻塞；
- 老格式 ``observations.jsonl`` 首次读取时自动迁移。

这样文件大小恒定（实测 16 个商人 28 KB），不再随时间变慢。
"""

import atexit
import json
import os
import threading
import time
from pathlib import Path

from . import paths as paths_module

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = paths_module.trade_dir() / "observations.json"

#: 墙钟下界（约 2001-09-09）。``time.monotonic()`` 是"开机以来秒数"，正常远小于
#: 这个值；低于它的 ``t`` 只可能是旧版本用 monotonic 落盘的遗留。
MIN_WALL_CLOCK = 1_000_000_000

#: 后台写盘间隔（秒）
FLUSH_INTERVAL = 5.0

#: 过期多久的货架周期直接从内存里丢掉（秒）
KEEP_AFTER_EXPIRY = 300.0


def is_wall_clock(value):
    """这个时刻像不像墙钟（``time.time()``）？"""
    try:
        return float(value) >= MIN_WALL_CLOCK
    except (TypeError, ValueError):
        return False


def _wall_now(value):
    """把调用方给的时刻统一成墙钟。

    缺省、读不出来、或明显是 monotonic（``< MIN_WALL_CLOCK``）时一律用
    ``time.time()``：落盘的时间戳必须能与下一次开机的时间比较。
    """
    if not is_wall_clock(value):
        return time.time()
    return float(value)


class Ledger:
    def __init__(self, path=None):
        self.path = Path(path or DEFAULT_PATH)
        self._lock = threading.RLock()
        self._merchants = {}          # merchant_id -> {"map", "merchant", "kind", "cycles"}
        self._loaded = False
        self._dirty = False
        self._flusher = None

    # ---------------------------------------------------------------- 写
    def record(self, visit, now=None):
        """存一条观察；visit 是 shop.Visit 或它的 to_dict()。

        ``now`` 是墙钟时刻；传进来 monotonic（旧调用方）时会被换成
        ``time.time()``，返回的 payload 里 ``t`` 就是实际记录的值。

        只改内存；磁盘由后台线程定期落盘（见 :meth:`flush`）。
        """
        payload = visit.to_dict() if hasattr(visit, "to_dict") else dict(visit)
        moment = _wall_now(now)
        payload["t"] = moment
        self._merge(payload, moment)
        self._start_flusher()
        return payload

    def _merge(self, payload, moment):
        merchant_id = str(payload.get("merchant_id") or "")
        # 随机商人没有 id：按地图分开存，别让不同地图的随机商人挤成一条
        key = merchant_id or f"anon:{payload.get('map') or ''}"
        refresh = float(payload.get("refresh_in") or 0)
        cycle_key = f"{int(round(moment + refresh))}"      # 同一个刷新时刻 = 同一货架
        with self._lock:
            self._load_once()
            entry = self._merchants.setdefault(
                key, {"id": merchant_id, "map": "", "merchant": "", "kind": "",
                      "cycles": {}})
            entry["map"] = payload.get("map") or entry["map"]
            entry["merchant"] = (payload.get("merchant")
                                 or payload.get("game_name") or entry["merchant"])
            entry["kind"] = payload.get("merchant_kind") or entry["kind"]
            cycle = entry["cycles"].setdefault(
                cycle_key, {"t": moment, "refresh_in": refresh, "rows": {}})
            if moment > cycle["t"]:
                cycle["t"] = moment
            cycle["refresh_in"] = max(refresh, cycle["refresh_in"])
            for row in payload.get("rows") or []:
                good_id = str(row.get("good_id") or "")
                side = str(row.get("side") or "")
                price = row.get("price")
                if not good_id or not side or price is None:
                    continue
                cycle["rows"][f"{good_id}|{side}"] = int(price)
            self._prune_locked(moment)
            self._dirty = True

    def _prune_locked(self, moment):
        """丢掉过期太久的货架周期——每个商人只保留当前（和刚换下的）。"""
        for entry in self._merchants.values():
            dead = [key for key, cycle in entry["cycles"].items()
                    if cycle["t"] + cycle["refresh_in"] < moment - KEEP_AFTER_EXPIRY]
            for key in dead:
                entry["cycles"].pop(key, None)

    # ---------------------------------------------------------------- 读
    def load(self):
        """当前记录，形状和旧版一致：``[{merchant_id, map, rows: [...]}, ...]``。"""
        with self._lock:
            self._load_once()
            out = []
            for merchant_id, entry in self._merchants.items():
                for cycle in entry["cycles"].values():
                    rows = []
                    for key, price in cycle["rows"].items():
                        good_id, _, side = key.partition("|")
                        rows.append({"good_id": good_id, "side": side, "price": price})
                    if not rows:
                        continue
                    out.append({
                        "merchant_id": entry.get("id", merchant_id),
                        "merchant": entry["merchant"],
                        "game_name": entry["merchant"],
                        "merchant_kind": entry["kind"],
                        "map": entry["map"],
                        "t": cycle["t"],
                        "refresh_in": cycle["refresh_in"],
                        "rows": rows,
                    })
            return out

    def _load_once(self):
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            # 老格式（observations.jsonl）还在的话，迁移进来，下次落盘写成新格式
            legacy = self.path.with_suffix(".jsonl")
            if legacy != self.path and legacy.exists():
                try:
                    self._hydrate_lines(legacy.read_text(encoding="utf-8"))
                    self._dirty = True
                except Exception:
                    pass
            return
        try:
            text = self.path.read_text(encoding="utf-8")
        except Exception:
            return
        if not text.strip():
            return
        payload = None
        try:
            payload = json.loads(text)
        except Exception:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("merchants"), dict):
            self._hydrate(payload["merchants"])
            return
        # 老格式（每行一条），或者测试里直接写进来的 JSONL
        self._hydrate_lines(text)

    def _hydrate(self, merchants):
        for merchant_id, entry in merchants.items():
            cycles = {}
            for key, cycle in (entry.get("cycles") or {}).items():
                rows = dict(cycle.get("rows") or {})
                if not rows:
                    continue
                cycles[str(key)] = {
                    "t": float(cycle.get("t") or 0),
                    "refresh_in": float(cycle.get("refresh_in") or 0),
                    "rows": rows,
                }
            if cycles:
                self._merchants[str(merchant_id)] = {
                    "id": entry.get("id", str(merchant_id)),
                    "map": entry.get("map") or "",
                    "merchant": entry.get("merchant") or "",
                    "kind": entry.get("kind") or "",
                    "cycles": cycles,
                }

    def _hydrate_lines(self, text):
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                observation = json.loads(line)
            except Exception:
                continue
            if not isinstance(observation, dict):
                continue
            if not is_wall_clock(observation.get("t", 0)):
                continue                     # 旧版 monotonic 记录，跨进程无意义
            self._merge(observation, float(observation.get("t", 0)))

    # ------------------------------------------------------------ 落盘
    def _start_flusher(self):
        if self._flusher is not None:
            return
        with self._lock:
            if self._flusher is not None:
                return
            thread = threading.Thread(target=self._flush_loop, name="ledger-flush",
                                      daemon=True)
            self._flusher = thread
            thread.start()
            atexit.register(self.flush)

    def _flush_loop(self):
        while True:
            time.sleep(FLUSH_INTERVAL)
            try:
                self.flush()
            except Exception:
                pass

    def flush(self):
        """把内存里的记录写到磁盘（原子替换，保留一份 .bak）。"""
        with self._lock:
            if not self._dirty:
                return False
            payload = {"version": 1, "merchants": {}}
            for merchant_id, entry in self._merchants.items():
                payload["merchants"][merchant_id] = {
                    "id": entry.get("id", ""),
                    "map": entry["map"],
                    "merchant": entry["merchant"],
                    "kind": entry["kind"],
                    "cycles": {key: {"t": cycle["t"],
                                     "refresh_in": cycle["refresh_in"],
                                     "rows": dict(cycle["rows"])}
                               for key, cycle in entry["cycles"].items()},
                }
            text = json.dumps(payload, ensure_ascii=False)
            path = self.path
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_text(text, encoding="utf-8")
                if path.exists():
                    backup = path.with_suffix(path.suffix + ".bak")
                    os.replace(str(path), str(backup))
                os.replace(str(tmp), str(path))
            except Exception:
                return False
            self._dirty = False
            return True

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
