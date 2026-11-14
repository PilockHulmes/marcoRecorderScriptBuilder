"""走图（过图）时间估算：纯逻辑，不碰游戏窗口、不截屏。

背景
----
跑商时工具会监控玩家的"过图"：从地图 A 进入地图 B。这里只统计**移动段**：
角色开始移动到切图完成，**包含黑屏 loading**（loading 期间活动倒计时也在走），
角色站着不动的时间不计入。调用方检测到一次过图后调用 :meth:`TravelTimes.add`。

地图用调用方传入的稳定 id（由小地图名字图比对得到），本模块只当成字符串 key，
不关心它长什么样。

数据分层
--------
- **个人样本**：每个用户本地积累，默认写在 ``data/travel_times.json``；
- **基准值**：作者自己跑出来随程序附带的冷启动数据，默认读
  ``data/travel_baseline.json``。未知地图/未知边先用基准值兜底。

估算规则（n = 这条边的个人样本数）
----------------------------------
::

    n >= 20   max(中位数, p90)                personal_p90      high
    n >= 5    中位数                          personal_median   medium
    n >= 1    中位数与基准值按 n/5 加权       personal_median   low
    n == 0    基准值；没有基准值就用 25 秒    baseline/default  low

n 为 1~4 时个人数据太少，直接用中位数容易被一次偶然的慢/快过图带偏，所以按
``n/5`` 的权重把个人中位数和基准值混合：n=1 只信个人 20%，n=4 信 80%。
没有基准值时直接采用个人中位数（仍然标 low）。

存储格式
--------
个人数据（显式 UTF-8、``ensure_ascii=False``、``indent=2``、原子写）::

    {
      "version": 1,
      "edges": [
        {"from": "射手村", "to": "魔法密林", "samples": [41.2, 39.8]}
      ]
    }

基准文件用同样的 ``edges`` 结构，但字段是 ``seconds`` 而不是 ``samples``；
另外也接受 ``{"射手村": {"魔法密林": 41.2}}`` 的嵌套写法和
``{"射手村->魔法密林": 41.2}`` 的扁平写法，方便手改。

示例::

    times = TravelTimes()
    times.add("射手村", "魔法密林", 41.2)
    times.walk_seconds("射手村", "魔法密林")
    times.round_trip("射手村", "魔法密林")
    times.save()
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

_LOG = logging.getLogger(__name__)

#: 仓库根目录（不依赖当前工作目录）
ROOT = Path(__file__).resolve().parents[1]

#: 个人走图数据的默认路径
DEFAULT_STORE_PATH = ROOT / "data" / "travel_times.json"

#: 随程序附带的基准值路径
DEFAULT_BASELINE_PATH = ROOT / "data" / "travel_baseline.json"

#: 既无个人样本、也无基准值时的保守默认值（秒）
DEFAULT_SECONDS = 25.0

#: 单条样本的合理上限（秒）；超过视为异常值丢弃
MAX_SECONDS = 600.0

#: 达到这个样本数就用中位数（medium）
MEDIUM_SAMPLES = 5

#: 达到这个样本数就用 max(中位数, p90)（high）
HIGH_SAMPLES = 20

#: 1~4 条样本时，个人数据占的权重分母：n / 5
WEIGHT_DENOMINATOR = 5.0

#: 中位数与基准值混合时使用的分位数
P90 = 0.9

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


# ---------------------------------------------------------------- 小工具
def _clean_map(value):
    """把地图 id 规整成非空字符串；非法返回 None。"""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _edge_key(from_map, to_map):
    """返回 ``(from, to)``；任一地图非法时返回 None。"""
    source = _clean_map(from_map)
    target = _clean_map(to_map)
    if source is None or target is None:
        return None
    return source, target


def _coerce_seconds(value, upper=MAX_SECONDS):
    """把数值规整成有限正 float；非数值/非正数/超上限返回 None。

    样本用 ``upper=MAX_SECONDS``（>600 秒算异常）；基准值是作者手工确认过的，
    只要求是有限正数，不设上限。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0.0:
        return None
    if upper is not None and seconds > upper:
        return None
    return seconds


def _median(values):
    """中位数；空列表返回 0.0。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _percentile(values, fraction):
    """线性插值分位数（fraction 取 0~1）；空列表返回 0.0。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = fraction * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[int(rank)])
    weight = rank - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def _weaker_confidence(first, second):
    """两个 confidence 里取更弱的那个。"""
    return first if _CONFIDENCE_RANK.get(first, -1) <= _CONFIDENCE_RANK.get(second, -1) else second


# ---------------------------------------------------------------- 基准值解析
def _baseline_pair(key):
    """从 ``(a, b)`` / ``"a->b"`` / ``"a→b"`` 形式的 key 里取出地图对。"""
    if isinstance(key, (tuple, list)) and len(key) == 2:
        source = _clean_map(key[0])
        target = _clean_map(key[1])
        if source is not None and target is not None:
            return source, target
        return None
    if isinstance(key, str):
        for separator in ("->", "→", "=>"):
            if separator in key:
                source, target = key.split(separator, 1)
                source = _clean_map(source)
                target = _clean_map(target)
                if source is not None and target is not None:
                    return source, target
    return None


def _baseline_from_entries(entries):
    """解析 ``[{"from", "to", "seconds"}, ...]``。"""
    result = {}
    if not isinstance(entries, list):
        return result
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        pair = _edge_key(entry.get("from"), entry.get("to"))
        seconds = _coerce_seconds(entry.get("seconds", entry.get("time")), upper=None)
        if pair is not None and seconds is not None:
            result[pair] = seconds
    return result


def _baseline_from_mapping(raw):
    """解析 ``{(a, b): seconds}`` 或 ``{a: {b: seconds}}`` 或 ``{"a->b": seconds}``。"""
    result = {}
    for key, value in raw.items():
        if isinstance(value, Mapping):
            source = _clean_map(key)
            if source is None:
                continue
            for target_key, seconds in value.items():
                target = _clean_map(target_key)
                seconds = _coerce_seconds(seconds, upper=None)
                if target is not None and seconds is not None:
                    result[(source, target)] = seconds
            continue
        pair = _baseline_pair(key)
        seconds = _coerce_seconds(value, upper=None)
        if pair is not None and seconds is not None:
            result[pair] = seconds
    return result


def _parse_baseline(raw):
    """把基准文件的顶层结构解析成 ``{(from, to): seconds}``。"""
    if isinstance(raw, Mapping):
        if isinstance(raw.get("edges"), list):
            return _baseline_from_entries(raw["edges"])
        return _baseline_from_mapping(raw)
    if isinstance(raw, list):
        return _baseline_from_entries(raw)
    return {}


def _load_baseline_file(path):
    """读基准文件；不存在/坏文件都返回空 dict（坏文件记一条 warning）。"""
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _LOG.warning("基准文件读不出来，忽略: %s (%s)", path, exc)
        return {}
    return _parse_baseline(raw)


# ---------------------------------------------------------------- 个人数据解析
def _parse_store(raw):
    """把个人数据文件的顶层结构解析成 ``{(from, to): [seconds, ...]}``。"""
    if isinstance(raw, Mapping):
        raw = raw.get("edges")
    if not isinstance(raw, list):
        return {}

    result = {}
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        pair = _edge_key(entry.get("from"), entry.get("to"))
        values = entry.get("samples")
        if pair is None or not isinstance(values, list):
            continue
        bucket = result.setdefault(pair, [])
        for value in values:
            seconds = _coerce_seconds(value)
            if seconds is not None:
                bucket.append(seconds)
    return {key: values for key, values in result.items() if values}


# ---------------------------------------------------------------- 主体
class TravelTimes:
    """个人走图样本 + 基准值的估算器。

    :param store_path: 个人数据 JSON 路径；默认 ``data/travel_times.json``。
                       相对路径按当前工作目录解析；构造时会自动 :meth:`load`。
    :param baseline: 基准值 ``{(from_map, to_map): seconds}``；传 ``None`` 时
                     尝试读 ``data/travel_baseline.json``，文件不存在则为空。
                     传 ``{}`` 表示明确"没有基准值"。
    :param max_samples: 每条边最多保留最近多少条样本（默认 50）。

    :raises ValueError: ``max_samples`` 不是 >= 1 的整数。
    :raises TypeError: ``baseline`` 既不是 dict/list 也不是 None。
    """

    def __init__(self, store_path=None, baseline=None, max_samples=50):
        self.store_path = Path(store_path) if store_path is not None else DEFAULT_STORE_PATH
        try:
            max_samples = int(max_samples)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"max_samples 应为整数: {max_samples!r}") from exc
        if max_samples < 1:
            raise ValueError(f"max_samples 至少为 1: {max_samples}")
        self.max_samples = max_samples

        if baseline is None:
            self._baseline = _load_baseline_file(DEFAULT_BASELINE_PATH)
        elif isinstance(baseline, Mapping):
            self._baseline = _parse_baseline(baseline)
        elif isinstance(baseline, list):
            self._baseline = _baseline_from_entries(baseline)
        else:
            raise TypeError(f"baseline 应为 dict 或 None: {type(baseline).__name__}")

        self._samples = {}
        self.load()

    # ------------------------------------------------------------ 样本
    def add(self, from_map, to_map, seconds):
        """追加一条样本。

        非数值、非正数、超过 600 秒、NaN/Inf 一律丢弃；地图 id 非法也丢弃。
        超过 ``max_samples`` 时丢最旧的那条。
        """
        pair = _edge_key(from_map, to_map)
        if pair is None:
            return
        value = _coerce_seconds(seconds)
        if value is None:
            return
        bucket = self._samples.setdefault(pair, [])
        bucket.append(value)
        if len(bucket) > self.max_samples:
            del bucket[: len(bucket) - self.max_samples]

    def samples(self, from_map, to_map):
        """返回这条边的样本副本（按写入顺序，旧 → 新）；未知边返回空列表。"""
        pair = _edge_key(from_map, to_map)
        if pair is None:
            return []
        return list(self._samples.get(pair, []))

    # ------------------------------------------------------------ 估算
    def estimate(self, from_map, to_map):
        """估算单向走图时间。

        :return: ``{"seconds": float, "source": str, "n": int, "confidence": str}``

        ``source`` 取值：

        - ``personal_p90``：n >= 20，取 max(中位数, p90)，confidence=high；
        - ``personal_median``：n >= 5 用中位数（medium）；1 <= n < 5 与基准值
          按 ``n/5`` 加权（low）；
        - ``baseline``：没有个人样本但有基准值（low）；
        - ``default``：两者都没有，用 :data:`DEFAULT_SECONDS`（low）。
        """
        pair = _edge_key(from_map, to_map)
        if pair is None:
            values = []
            baseline = None
        else:
            values = self._samples.get(pair, [])
            baseline = self._baseline.get(pair)

        count = len(values)
        if count >= HIGH_SAMPLES:
            median = _median(values)
            p90 = _percentile(values, P90)
            return {
                "seconds": float(max(median, p90)),
                "source": "personal_p90",
                "n": count,
                "confidence": "high",
            }

        if count >= MEDIUM_SAMPLES:
            return {
                "seconds": _median(values),
                "source": "personal_median",
                "n": count,
                "confidence": "medium",
            }

        if count >= 1:
            median = _median(values)
            if baseline is None:
                seconds = median
            else:
                personal_weight = min(1.0, count / WEIGHT_DENOMINATOR)
                seconds = median * personal_weight + baseline * (1.0 - personal_weight)
            return {
                "seconds": float(seconds),
                "source": "personal_median",
                "n": count,
                "confidence": "low",
            }

        if baseline is not None:
            return {
                "seconds": float(baseline),
                "source": "baseline",
                "n": 0,
                "confidence": "low",
            }

        return {
            "seconds": DEFAULT_SECONDS,
            "source": "default",
            "n": 0,
            "confidence": "low",
        }

    def walk_seconds(self, from_map, to_map):
        """只要估算出来的秒数（float）。"""
        return float(self.estimate(from_map, to_map)["seconds"])

    def round_trip(self, a, b):
        """往返时间 = ``estimate(a, b)`` + ``estimate(b, a)``。

        :return: ``{"seconds", "source", "confidence", "n", "forward", "backward"}``

        两个方向 source 相同就沿用，不同则标 ``mixed``；confidence 取更弱的一侧。
        """
        forward = self.estimate(a, b)
        backward = self.estimate(b, a)
        return {
            "seconds": float(forward["seconds"] + backward["seconds"]),
            "source": forward["source"] if forward["source"] == backward["source"] else "mixed",
            "confidence": _weaker_confidence(forward["confidence"], backward["confidence"]),
            "n": forward["n"] + backward["n"],
            "forward": forward,
            "backward": backward,
        }

    # ------------------------------------------------------------ 持久化
    def save(self):
        """原子写个人数据：先写同目录临时文件，再 ``os.replace`` 覆盖。"""
        payload = {
            "version": 1,
            "edges": [
                {"from": source, "to": target, "samples": list(values)}
                for (source, target), values in sorted(self._samples.items())
                if values
            ],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

        path = self.store_path
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        except BaseException:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    def load(self):
        """从 ``store_path`` 读个人数据；文件不存在则清空。

        文件坏掉（JSON 解析失败/读不了）时保留当前内存数据并记 warning，
        不把用户的本地样本清空。
        """
        path = self.store_path
        if not path.is_file():
            self._samples = {}
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _LOG.warning("个人走图数据读不出来，保留当前内存数据: %s (%s)", path, exc)
            return

        loaded = _parse_store(raw)
        for pair, values in loaded.items():
            if len(values) > self.max_samples:
                loaded[pair] = values[-self.max_samples:]
        self._samples = loaded

    # ------------------------------------------------------------ 汇总
    def stats(self):
        """个人数据的统计。

        - ``edges``：有样本的边数；
        - ``samples``：样本总数；
        - ``maps``：出现过的不同地图数；
        - ``with_baseline``：这些边里，有基准值兜底的边数。
        """
        edges = {pair: values for pair, values in self._samples.items() if values}
        maps = set()
        for source, target in edges:
            maps.add(source)
            maps.add(target)
        with_baseline = sum(1 for pair in edges if pair in self._baseline)
        return {
            "edges": len(edges),
            "samples": sum(len(values) for values in edges.values()),
            "maps": len(maps),
            "with_baseline": with_baseline,
        }

    def edges(self):
        """列出所有有样本的边：``[{"from", "to", "n", "median"}, ...]``。

        按 ``(from, to)`` 排序，保证输出稳定。
        """
        rows = []
        for (source, target), values in sorted(self._samples.items()):
            if not values:
                continue
            rows.append({
                "from": source,
                "to": target,
                "n": len(values),
                "median": _median(values),
            })
        return rows


__all__ = [
    "TravelTimes",
    "DEFAULT_SECONDS",
    "DEFAULT_STORE_PATH",
    "DEFAULT_BASELINE_PATH",
    "MAX_SECONDS",
]
