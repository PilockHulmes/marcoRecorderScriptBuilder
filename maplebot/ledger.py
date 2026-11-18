"""观察记录簿：把每次打开商店的结果存下来，并回答"这个价还有效吗"。

有效期模型：**每个商人只存一组**

    deadline = 观察时刻 + 商店倒计时剩余秒数      ← 这一轮商店几点刷新

- ``deadline > 现在``：这一组价格有效，看板显示价格和剩余时间；
- ``deadline <= 现在``：整组作废，看板显示"已过期"。

同一轮商店里反复观察（滚动读取）时**合并**行；发现倒计时明显跳高
（超过 :data:`REFRESH_MARGIN`）才认为是商店刷新了，清空旧行重新开始。

早期版本存过"多个货架周期"，遇到那种旧格式直接丢弃——价格几分钟就过期，
重新读一次就有了（见 TRADE_DESIGN.md 31）。

存储：内存里是 ``商人 -> {deadline, rows}``，磁盘上是 ``observations.json``，
后台线程每 5 秒原子落盘一次（保留一份 .bak）。
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

#: 过期多久之后把整条记录丢掉（秒）
KEEP_AFTER_EXPIRY = 300.0

#: 新算出的刷新时刻要比当前晚这么多秒，才认为商店刷新了（秒）。
#: 倒计时只能一秒一秒减，正常重算不会变大；只有刷新才会跳到 3~6 分钟。
REFRESH_MARGIN = 20.0

#: 新算出的刷新时刻比当前**早**这么多秒，说明存着的那次读错了（比如把 00:59
#: 读成 03:58）：同一轮里重算不会差这么多，直接以这次为准。
CORRECT_MARGIN = 30.0


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
        #: key -> {"id","map","merchant","kind","deadline","t","rows"}
        self._merchants = {}
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
        with self._lock:
            self._load_once()
            entry = self._merchants.setdefault(
                key, {"id": merchant_id, "map": "", "merchant": "", "kind": "",
                      "deadline": 0.0, "t": 0.0, "rows": {}})
            entry["map"] = payload.get("map") or entry["map"]
            entry["merchant"] = (payload.get("merchant")
                                 or payload.get("game_name") or entry["merchant"])
            entry["kind"] = payload.get("merchant_kind") or entry["kind"]

            if refresh > 0:
                estimate = moment + refresh
                current = float(entry.get("deadline") or 0)
                if not current or estimate > current + REFRESH_MARGIN:
                    # 商店刷新了：上一轮的商品全部作废
                    entry["rows"] = {}
                    entry["deadline"] = estimate
                elif estimate < current - CORRECT_MARGIN:
                    # 存着的到期时刻明显偏晚（之前读错过）→ 以这次为准，
                    # 否则那个错误会一直粘着，看板永远多显示几分钟
                    entry["deadline"] = estimate
                # 同一轮：保留已经确定的刷新时刻。
                # 倒计时读错（比如 3:07 读成 2:07）只会让这次的数字变小，
                # 不能让它改写刷新时刻，否则同一轮会被拆成两轮（实测踩过）。
            entry["t"] = moment
            deadline = float(entry.get("deadline") or 0)
            row_refresh = max(0.0, deadline - moment) if deadline else 0.0
            for row in payload.get("rows") or []:
                good_id = str(row.get("good_id") or "")
                side = str(row.get("side") or "")
                price = row.get("price")
                if not good_id or not side or price is None:
                    continue
                entry["rows"][f"{good_id}|{side}"] = {
                    "p": int(price), "t": moment, "r": row_refresh, "src": "local"}
            self._prune_locked(moment)
            self._dirty = True

    def _prune_locked(self, moment):
        """过期太久的商人记录整条丢掉（只留最近 5 分钟）。"""
        dead = [key for key, entry in self._merchants.items()
                if float(entry.get("deadline") or 0) < moment - KEEP_AFTER_EXPIRY]
        for key in dead:
            self._merchants.pop(key, None)

    # ---------------------------------------------------------------- 读
    def load(self):
        """当前记录：``[{merchant_id, map, deadline, rows: [...]}, ...]``。

        每个商人最多一条。
        """
        with self._lock:
            self._load_once()
            out = []
            for merchant_id, entry in self._merchants.items():
                rows = []
                for key, stored in (entry.get("rows") or {}).items():
                    good_id, _, side = key.partition("|")
                    price = stored.get("p") if isinstance(stored, dict) else stored
                    if price is None:
                        continue
                    rows.append({"good_id": good_id, "side": side, "price": int(price)})
                if not rows:
                    continue
                deadline = float(entry.get("deadline") or 0)
                observed = float(entry.get("t") or 0)
                out.append({
                    "merchant_id": entry.get("id", merchant_id),
                    "merchant": entry.get("merchant", ""),
                    "game_name": entry.get("merchant", ""),
                    "merchant_kind": entry.get("kind", ""),
                    "map": entry.get("map", ""),
                    "t": observed,
                    "refresh_in": max(0.0, deadline - observed) if deadline else 0.0,
                    "deadline": deadline,
                    "rows": rows,
                })
            return out

    def _load_once(self):
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        try:
            text = self.path.read_text(encoding="utf-8")
        except Exception:
            return
        if not text.strip():
            return
        try:
            payload = json.loads(text)
        except Exception:
            return
        if not (isinstance(payload, dict) and isinstance(payload.get("merchants"), dict)):
            return
        merchants = payload["merchants"]
        if any(isinstance(item, dict) and "cycles" in item for item in merchants.values()):
            # 旧格式（一个商人存多轮）——按约定直接丢弃：价格几分钟就过期，
            # 重新读一次商店就有了。删掉文件，免得下次还被误读。
            try:
                self.path.unlink()
            except OSError:
                pass
            return
        self._hydrate(merchants)

    def _hydrate(self, merchants):
        for merchant_id, entry in merchants.items():
            if not isinstance(entry, dict):
                continue
            rows = {}
            for row_key, stored in (entry.get("rows") or {}).items():
                if isinstance(stored, dict):
                    rows[row_key] = stored
                elif stored is not None:
                    rows[row_key] = {"p": int(stored),
                                     "t": float(entry.get("t") or 0),
                                     "r": float(entry.get("refresh_in") or 0),
                                     "src": "local"}
            if not rows:
                continue
            self._merchants[str(merchant_id)] = {
                "id": entry.get("id", str(merchant_id)),
                "map": entry.get("map") or "",
                "merchant": entry.get("merchant") or "",
                "kind": entry.get("kind") or "",
                "deadline": float(entry.get("deadline") or 0),
                "t": float(entry.get("t") or 0),
                "rows": rows,
            }

    # ------------------------------------------------------------ 共享
    def merchant_record(self, merchant_id):
        """把某个商人**本地观察**的行导出成共享格式（远端来的行不导出）。"""
        with self._lock:
            self._load_once()
            entry = self._merchants.get(merchant_id)
            if not entry:
                return None
            rows = {}
            for key, row in (entry.get("rows") or {}).items():
                if not isinstance(row, dict) or row.get("src") != "local":
                    continue
                rows[key] = {"p": int(row.get("p", 0)),
                             "t": float(row.get("t", 0)),
                             "r": float(row.get("r", 0))}
            if not rows:
                return None
            return {"v": 1, "merchant_id": merchant_id, "map": entry.get("map", ""),
                    "writer": "", "rev": 0, "rows": rows}

    def apply_remote(self, merchant_id, record):
        """把合并好的远端记录并进本地（标记来源 remote，下次不会重复上传）。"""
        if not record or not record.get("rows"):
            return False
        rows = record["rows"]
        deadline = max((float(r.get("t", 0)) + float(r.get("r", 0)))
                       for r in rows.values())
        with self._lock:
            self._load_once()
            entry = self._merchants.setdefault(
                merchant_id, {"id": merchant_id, "map": "", "merchant": "",
                              "kind": "", "deadline": 0.0, "t": 0.0, "rows": {}})
            if record.get("map"):
                entry["map"] = record["map"]
            current = float(entry.get("deadline") or 0)
            if not current or deadline > current + REFRESH_MARGIN:
                # 远端是更新的一轮：本地旧行作废
                entry["rows"] = {}
                entry["deadline"] = deadline
            else:
                entry["deadline"] = max(current, deadline)
            newest = float(entry.get("t") or 0)
            for key, row in rows.items():
                row_t = float(row.get("t", 0))
                previous = entry["rows"].get(key)
                if previous is not None and float(previous.get("t", 0)) > row_t:
                    continue                     # 本地这条更新，保留本地的
                entry["rows"][key] = {"p": int(row.get("p", 0)), "t": row_t,
                                      "r": float(row.get("r", 0)), "src": "remote"}
                newest = max(newest, row_t)
            entry["t"] = newest
            self._dirty = True
            return True

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
            payload = {"version": 2, "merchants": {}}
            for merchant_id, entry in self._merchants.items():
                payload["merchants"][merchant_id] = {
                    "id": entry.get("id", ""),
                    "map": entry.get("map", ""),
                    "merchant": entry.get("merchant", ""),
                    "kind": entry.get("kind", ""),
                    "deadline": float(entry.get("deadline") or 0),
                    "t": float(entry.get("t") or 0),
                    "rows": dict(entry.get("rows") or {}),
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
        deadline = observation.get("deadline")
        if deadline is not None:
            try:
                return float(deadline)
            except (TypeError, ValueError):
                pass
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
