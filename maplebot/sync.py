"""多人共享"商人当前价格"的同步引擎（先不接网络：后端可替换）。

数据形状（每个商人一个对象，约 300 字节）：

    {
      "v": 1,
      "merchant_id": "dour_4",
      "map": "孤獨的沙漠-1",
      "writer": "本机 uuid",          # 谁写的：用来跳过自己写的回显
      "rev": 7,                       # 本机自增，配合 writer 判断"是不是我写的"
      "rows": {                       # 货物行：good|side -> 价格 + 该行的有效期
        "mineral_water|sell": {"p": 19, "t": 1763360000.5, "r": 46.0}
      }
    }

合并规则（行级 last-write-wins）：

    * 同一行取 ``t`` 更大的；``t`` 相同则比 ``writer``（保证确定性）
    * 缺的行各自保留（"只看全了 2 行、后来才看全 3 行"就是这么合起来的）
    * 任何行 ``t + r < now`` 即过期，读的时候直接丢掉
    * ``t`` 超过 now + 容差（时钟漂移）时按 now 处理，防止别人用未来时间"钉住"数据

上传（事件驱动）：本地某商人数据变了 → 防抖 2 秒 → PUT 那个对象。
下载：按活跃度决定的间隔拉一次目录，只下载 etag 变了的商人。
"""

from __future__ import annotations

import time

#: 时钟漂移容差（秒）：别人机器的时间比我们快太多时，最多按 now + 这个值算
CLOCK_SKEW_LIMIT = 120.0

#: 上传防抖（秒）
UPLOAD_DEBOUNCE = 2.0

#: 请求失败后的退避（秒），依次取用
BACKOFF = (1.0, 3.0, 10.0, 30.0)


def now_seconds():
    return time.time()


# ------------------------------------------------------------------ 记录工具
def make_record(merchant_id, map_name, writer, rev, rows):
    """``rows`` 是 ``{"good|side": {"p": 19, "t": ..., "r": ...}}``。"""
    return {"v": 1, "merchant_id": merchant_id, "map": map_name,
            "writer": writer, "rev": int(rev), "rows": dict(rows)}


def valid_rows(record, now):
    """挑出仍然有效的行（``t + r >= now``）。"""
    out = {}
    for key, row in (record.get("rows") or {}).items():
        try:
            t = float(row["t"])
            r = float(row.get("r") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if t + r >= now:
            out[key] = {"p": int(row["p"]), "t": t, "r": r}
    return out


def _clamp(t, now):
    """别人时钟快太多时，别让它的时间"钉住"数据。"""
    return min(float(t), now + CLOCK_SKEW_LIMIT)


def merge_records(local, remote, now):
    """把远端记录合进本地记录，返回合并结果（行级 LWW）。"""
    merged = {}
    for source in (local, remote):
        if not source:
            continue
        for key, row in valid_rows(source, now).items():
            row = dict(row)
            row["t"] = _clamp(row["t"], now)
            row["w"] = source.get("writer", "")      # 平局时用它做确定性裁决
            current = merged.get(key)
            if current is None:
                merged[key] = row
                continue
            if (row["t"], row["w"]) > (current["t"], current.get("w", "")):
                merged[key] = row
    if not merged:
        return None
    newest = max(merged.values(), key=lambda r: r["t"])
    map_name = ""
    for source in (remote, local):
        if source and valid_rows(source, now):
            map_name = source.get("map") or map_name
            if map_name:
                break
    return {"v": 1, "merchant_id": (local or remote or {}).get("merchant_id", ""),
            "map": map_name, "writer": (local or remote or {}).get("writer", ""),
            "rev": int((local or remote or {}).get("rev", 0)),
            "rows": merged}


def same_rows(a, b):
    """两份记录的有效行是否完全一致（用来判断"要不要上传"）。"""
    if not a or not b:
        return a == b
    left = {k: (v["p"], round(v["t"], 3)) for k, v in (a.get("rows") or {}).items()}
    right = {k: (v["p"], round(v["t"], 3)) for k, v in (b.get("rows") or {}).items()}
    return left == right


# ------------------------------------------------------------------ 后端接口
class FakeBackend:
    """内存版"远端"：带 etag、条件写、故障注入。测试用它，接真 OSS 时换掉。"""

    def __init__(self):
        self.objects = {}          # merchant_id -> record
        self.etags = {}            # merchant_id -> etag
        self._counter = 0
        self.fail_next_put = 0     # 模拟"PUT 成功但响应丢了"
        self.fail_next_get = 0
        self.rate_limited = 0      # 模拟 429
        self.put_calls = 0
        self.get_calls = 0

    def _next_etag(self):
        self._counter += 1
        return f'"{self._counter}"'

    def list_objects(self):
        return dict(self.etags)

    def get(self, merchant_id):
        self.get_calls += 1
        if self.fail_next_get > 0:
            self.fail_next_get -= 1
            raise IOError("模拟下载失败")
        if merchant_id not in self.objects:
            return None, None
        return dict(self.objects[merchant_id]), self.etags.get(merchant_id)

    def put_if_match(self, merchant_id, record, etag):
        """条件写：etag 不匹配返回 False（相当于 412）。"""
        self.put_calls += 1
        if self.rate_limited > 0:
            self.rate_limited -= 1
            raise IOError("429")
        if self.fail_next_put > 0:
            # 写成功了，但客户端收不到响应
            self.fail_next_put -= 1
            self.objects[merchant_id] = dict(record)
            self.etags[merchant_id] = self._next_etag()
            raise IOError("响应丢失")
        if self.etags.get(merchant_id) != etag:
            return False
        self.objects[merchant_id] = dict(record)
        self.etags[merchant_id] = self._next_etag()
        return True


# ------------------------------------------------------------------ 引擎
class SyncEngine:
    """管"什么时候传、传什么、什么时候拉"。

    ``get_local(merchant_id)`` 返回本地记录（``make_record`` 的形状）或 None；
    ``apply_remote(merchant_id, record)`` 把合并后的远端行交给本地存储。
    """

    def __init__(self, backend, writer, get_local, apply_remote,
                 now=now_seconds):
        self.backend = backend
        self.writer = writer
        self._get_local = get_local
        self._apply = apply_remote
        self.now = now
        self._dirty = {}            # merchant_id -> 第一次变脏的时刻
        self._rev = 0
        self._etags = {}            # 上次见到的 etag
        self._backoff = 0
        self._next_attempt = 0.0
        self.stats = {"uploaded": 0, "downloaded": 0, "conflicts": 0,
                      "errors": 0, "skipped_self": 0}

    # -------------------------------------------------------------- 上传
    def mark_dirty(self, merchant_id):
        if merchant_id and merchant_id not in self._dirty:
            self._dirty[merchant_id] = self.now()

    def upload_due(self, now):
        """到点的上传。返回真正传上去的商人列表。"""
        if now < self._next_attempt:
            return []
        done = []
        for merchant_id in list(self._dirty):
            if now - self._dirty[merchant_id] < UPLOAD_DEBOUNCE:
                continue
            if self._upload_one(merchant_id, now):
                done.append(merchant_id)
            self._dirty.pop(merchant_id, None)
        return done

    def _upload_one(self, merchant_id, now):
        local = self._get_local(merchant_id)
        if not local or not valid_rows(local, now):
            return False
        record = self._bump(local)
        etag = self._etags.get(merchant_id)
        try:
            ok = self.backend.put_if_match(merchant_id, record, etag)
        except IOError as exc:
            if "429" in str(exc):
                self._backoff = min(self._backoff + 1, len(BACKOFF) - 1)
                self._next_attempt = now + BACKOFF[self._backoff]
                self.stats["errors"] += 1
                return False
            # 写可能成功了但响应丢了：读回来确认
            self.stats["errors"] += 1
            if self._confirm_written(merchant_id, record):
                self._etags[merchant_id] = self.backend.list_objects().get(merchant_id)
                self.stats["uploaded"] += 1
                return True
            self._next_attempt = now + BACKOFF[0]
            return False
        if ok:
            self._backoff = 0
            self._etags = self.backend.list_objects()
            self.stats["uploaded"] += 1
            return True
        # 冲突：别人先写了，合并后重试一次
        self.stats["conflicts"] += 1
        try:
            remote, remote_etag = self.backend.get(merchant_id)
        except IOError:
            return False
        merged = merge_records(local, remote, now)
        if merged is None:
            return False
        retry = self._bump(merged)
        try:
            ok = self.backend.put_if_match(merchant_id, retry, remote_etag)
        except IOError:
            self.stats["errors"] += 1
            return False
        if ok:
            self._etags = self.backend.list_objects()
            self.stats["uploaded"] += 1
            return True
        return False

    def _bump(self, record):
        self._rev += 1
        out = dict(record)
        out["writer"] = self.writer
        out["rev"] = self._rev
        return out

    def _confirm_written(self, merchant_id, record):
        try:
            remote, etag = self.backend.get(merchant_id)
        except IOError:
            return False
        if not remote:
            return False
        return (remote.get("writer") == record.get("writer")
                and int(remote.get("rev", 0)) >= int(record.get("rev", 0)))

    # -------------------------------------------------------------- 下载
    def poll(self, now):
        """拉一次目录，只下载 etag 变了的商人。返回被合并的商人列表。"""
        try:
            listing = self.backend.list_objects()
        except IOError:
            self.stats["errors"] += 1
            return []
        changed = []
        for merchant_id, etag in listing.items():
            if self._etags.get(merchant_id) == etag:
                continue                       # 没变，不下载
            try:
                remote, remote_etag = self.backend.get(merchant_id)
            except IOError:
                self.stats["errors"] += 1
                continue
            if not remote:
                continue
            self._etags[merchant_id] = remote_etag
            if remote.get("writer") == self.writer:
                self.stats["skipped_self"] += 1     # 自己写的，不重复合并
                continue
            local = self._get_local(merchant_id)
            merged = merge_records(local, remote, now)
            if merged is None:
                continue
            self._apply(merchant_id, merged)
            self.stats["downloaded"] += 1
            changed.append(merchant_id)
        return changed
