"""跑商控制台视图：地图跟踪 + 读商店/货舱 + 三级建议，全部调用共享会话。

逻辑在 :class:`maplebot.session.TradeSession`（GUI 用的是同一个类），这里只
做两件事：

- 每帧把画面交给 ``TradeSession.update``（必要时按 ``advice_every`` 放慢读取）；
- 把返回的 :class:`~maplebot.session.State` 格式化成控制台文本行：
  ``[商店] …``、``[货舱] …`` 和三级建议文本。

行为（TRADE_DESIGN.md 13）：

- 一直在跑，跟踪"当前在哪个图"
- 检测购物界面是否打开：打开的那一帧读一次、记录一次、给一次建议
- 界面开着时每隔 `advice_every` 秒重算一次（玩家可能刚滚出新的商品）
- 界面关掉就什么都不说
"""

import time
from dataclasses import dataclass

import numpy as np

from . import advice as advice_module
from . import ledger as ledger_module
from . import mapwatch
from . import trade
from .session import TradeSession


def cargo_open(frame):
    try:
        return bool(trade.find_cargo_window(frame))
    except Exception:
        return False


def shop_open(frame):
    """购物界面是否打开（SHOP 窗口在）。"""
    try:
        return bool(trade.find_shop_window(frame))
    except Exception:
        return False


class _ConsoleSession(TradeSession):
    """控制台的窗口探测仍走模块级函数，测试可以直接打桩。"""

    def _shop_open(self, frame):
        return shop_open(frame)

    def _cargo_open(self, frame):
        return cargo_open(frame)


@dataclass
class Runtime:
    watcher: object = None
    ledger: object = None
    travel: object = None
    advice_every: float = 2.0
    emit: object = print
    session: object = None

    def __post_init__(self):
        self.watcher = self.watcher or mapwatch.MapWatcher()
        self.ledger = self.ledger or ledger_module.Ledger()
        self.travel = self.travel or advice_module.MapTravel()
        if self.session is None:
            self.session = _ConsoleSession(self.watcher, self.ledger, self.travel)
        # 控制台按 advice_every 放慢读取（GUI 用自己的 0.4s / 1.0s）
        self.session.shop_every = float(self.advice_every)
        self.session.cargo_every = float(self.advice_every)

    # ------------------------------------------------------------------
    def step(self, frame, now=None):
        """处理一帧；返回这一帧要对玩家说的话（可能为空）。"""
        now = time.monotonic() if now is None else float(now)
        state = self.session.update(frame, now)
        out = []
        if self.session.watcher_error:
            out.append(f"[runtime] 地图更新异常：{self.session.watcher_error}")
        if self.session.shop_error:
            out.append(f"[runtime] 读取商店失败：{self.session.shop_error}")
            return out
        if self.session.shop_read:
            visit = self.session.visit
            out.append(f"[商店] {visit.merchant or '(随机商人)'} @ {state.map}"
                       f"　金币 {visit.coins}　载重 {visit.weight}/{visit.capacity}")
            out.extend(state.advice)
            return out
        if self.session.cargo_error:
            out.append(f"[runtime] 读货舱失败：{self.session.cargo_error}")
            return out
        if self.session.cargo_read and self.session.held:
            out.append(f"[货舱] 身上 {len(self.session.held)} 种货")
            out.extend(f"  {line}" for line in state.cargo)
        return out


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
