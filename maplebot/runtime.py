"""跑商运行时：地图 watcher + 购物界面读取 + 记录 + 单跳建议。

行为（TRADE_DESIGN.md 13）：

- 一直在跑，跟踪"当前在哪个图"
- 检测购物界面是否打开：打开的那一帧读一次、记录一次、给一次建议
- 界面开着时每隔 `advice_every` 秒重算一次（玩家可能刚滚出新的商品）
- 界面关掉就什么都不说
"""

import time
from dataclasses import dataclass, field

import numpy as np

from . import advice as advice_module
from . import ledger as ledger_module
from . import mapwatch
from . import shop
from . import trade


def shop_open(frame):
    """购物界面是否打开（SHOP 窗口在）。"""
    try:
        return bool(trade.find_shop_window(frame))
    except Exception:
        return False


def _good_name(good_id):
    try:
        return shop.load_goods().get(good_id, {}).get("name", good_id)
    except Exception:
        return good_id


@dataclass
class Runtime:
    watcher: object = None
    ledger: object = None
    travel: object = None
    advice_every: float = 2.0
    emit: object = print

    _open: bool = False
    _last_advice: float = 0.0
    _merged: dict = field(default_factory=dict)     # (good_id, side) -> price，跨滚动累积
    _messages: list = field(default_factory=list)

    def __post_init__(self):
        if self.watcher is None:
            self.watcher = mapwatch.MapWatcher()
        if self.ledger is None:
            self.ledger = ledger_module.Ledger()
        if self.travel is None:
            self.travel = advice_module.MapTravel()

    # ------------------------------------------------------------------
    def step(self, frame, now=None):
        """处理一帧；返回这一帧要对玩家说的话（可能为空）。"""
        now = time.monotonic() if now is None else float(now)
        out = []
        try:
            self.watcher.step(frame, now=now)
        except Exception as exc:
            out.append(f"[runtime] 地图更新异常：{exc}")

        current_map = self._current_map()
        opened = shop_open(frame)
        if not opened:
            self._open = False
            return out

        first = not self._open
        self._open = True
        if not first and now - self._last_advice < self.advice_every:
            return out
        self._last_advice = now

        try:
            visit = shop.read_visit(frame, current_map)
        except Exception as exc:
            out.append(f"[runtime] 读取商店失败：{exc}")
            return out

        if first:
            self._merged = {}

        # 滚动拼接：每次只看到 3 行，把多帧的 (商品, 方向) 合并起来
        before = len(self._merged)
        for row in visit.rows:
            self._merged[(row.good_id, row.side)] = row.price
        merged_rows = [shop.Row(good_id, _good_name(good_id), side, price)
                       for (good_id, side), price in self._merged.items()]
        if len(self._merged) > before or first:
            visit.rows = merged_rows
            try:
                self.ledger.record(visit, now=now)
            except Exception as exc:
                out.append(f"[runtime] 记录失败：{exc}")
        else:
            visit.rows = merged_rows

        out.append(f"[商店] {visit.merchant or '(随机商人)'} @ {current_map}"
                   f"　金币 {visit.coins}　载重 {visit.weight}/{visit.capacity}")
        if visit.rows:
            try:
                remaining = self._remaining_seconds(frame)
                items = advice_module.suggest(visit, self.ledger, self.travel,
                                              now=now, remaining=remaining)
                out.extend(advice_module.format_suggestions(items))
            except Exception as exc:
                out.append(f"[runtime] 建议计算失败：{exc}")
        return out

    # ------------------------------------------------------------------
    def _current_map(self):
        previous = getattr(self.watcher, "last_map_obs", None)
        return getattr(previous, "map_id", "") or ""

    def _remaining_seconds(self, frame):
        """本局剩余时间（秒）；读不到返回 None（不限制）。"""
        try:
            text = trade.read_remaining_time(frame)
            seconds = shop.countdown_seconds(text)
            return seconds or None
        except Exception:
            return None


def _grabber():
    import mss
    import win32gui

    best = None

    def callback(hwnd, _):
        nonlocal best
        if not win32gui.IsWindowVisible(hwnd) or win32gui.GetWindowText(hwnd) != "MapleStory":
            return
        rect = win32gui.GetWindowRect(hwnd)
        area = (rect[2] - rect[0]) * (rect[3] - rect[1])
        if best is None or area > best[0]:
            best = (area, hwnd)

    win32gui.EnumWindows(callback, None)
    if best is None:
        raise SystemExit("找不到 MapleStory 窗口")
    hwnd = best[1]
    ox, oy = win32gui.ClientToScreen(hwnd, (0, 0))
    cw, ch = win32gui.GetClientRect(hwnd)[2:]

    def grab():
        with mss.mss() as sct:
            shot = sct.grab({"left": ox, "top": oy, "width": cw, "height": ch})
            return np.array(shot)[:, :, :3].copy()

    return grab


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="跑商助手（只读）")
    parser.add_argument("--interval", type=float, default=0.1)
    parser.add_argument("--advice-every", type=float, default=2.0)
    args = parser.parse_args(argv)

    runtime = Runtime(advice_every=args.advice_every,
                      emit=lambda line: print(line, flush=True))
    grab = _grabber()
    print("跑商助手已启动，Ctrl+C 结束", flush=True)
    try:
        while True:
            for line in runtime.step(grab()):
                print(line, flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("停止", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
