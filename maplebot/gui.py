"""跑商助手 GUI：独立小窗，三块面板，分批刷新。

刷新节奏（详见 TRADE_DESIGN.md）：

    抓帧 / 地图跟踪     每 100ms
    读购物界面          0.4s（打开瞬间立刻读一次）
    读货舱              1.0s
    GUI 重绘            0.25s（数据没变就跳过）

逻辑与界面分离：`Controller` 只处理画面 -> 状态，测试不需要显示环境。
"""

import time
from dataclasses import dataclass, field

from . import advice as advice_module
from . import ledger as ledger_module
from . import mapwatch
from . import shop
from . import trade

SHOP_EVERY = 0.4
CARGO_EVERY = 1.0
REPAINT_EVERY = 0.25
BOARD_EVERY = 2.0


@dataclass
class State:
    map: str = ""
    advice: list = field(default_factory=list)
    cargo: list = field(default_factory=list)
    board: list = field(default_factory=list)
    note: str = ""
    version: int = 0


class Controller:
    def __init__(self, watcher=None, ledger=None, travel=None, now=None):
        self.watcher = watcher or mapwatch.MapWatcher()
        self.ledger = ledger or ledger_module.Ledger()
        self.travel = travel or advice_module.MapTravel()
        self.state = State()
        self._open = False
        self._shop_at = 0.0
        self._cargo_at = 0.0
        self._board_at = 0.0
        self._merged = {}

    # ------------------------------------------------------------------
    def current_map(self):
        previous = getattr(self.watcher, "last_map_obs", None)
        return getattr(previous, "map_id", "") or ""

    def update(self, frame, now=None):
        now = time.monotonic() if now is None else float(now)
        try:
            self.watcher.step(frame, now=now)
        except Exception:
            pass
        self.state.map = self.current_map()

        opened = _safe(trade.find_shop_window, frame, default=False)
        if opened:
            if not self._open or now - self._shop_at >= SHOP_EVERY:
                self._read_shop(frame, now)
                self._shop_at = now
            self._open = True
        else:
            self._open = False
            self._merged = {}
            if _safe(trade.find_cargo_window, frame, default=False):
                if now - self._cargo_at >= CARGO_EVERY:
                    self._read_cargo(frame, now)
                    self._cargo_at = now

        if now - self._board_at >= BOARD_EVERY:
            self._read_board(now)
            self._board_at = now
        return self.state

    # ------------------------------------------------------------------
    def _read_shop(self, frame, now):
        try:
            visit = shop.read_visit(frame, self.state.map)
        except Exception as exc:
            self.state.note = f"读商店失败：{exc}"
            return
        try:
            self.ledger.record(visit, now=now)
        except Exception:
            pass
        for row in visit.rows:
            self._merged[(row.good_id, row.side)] = row.price
        if self._merged:
            visit.rows = [shop.Row(g, _name(g), side, price)
                          for (g, side), price in self._merged.items()]
        lines = []
        try:
            items = advice_module.suggest(visit, self.ledger, self.travel, now=now)
            lines = advice_module.format_suggestions(items)
            if not items:
                explore = advice_module.explore_plan(self.ledger, self.travel,
                                                     now=now, current_map=self.state.map)
                for item in explore:
                    lines.append(f"去看看 {item['merchant']}({item['map']}) "
                                 f"{item['hops']} 张图")
        except Exception as exc:
            lines = [f"建议计算失败：{exc}"]
        self.state.advice = lines
        self.state.version += 1

    def _read_cargo(self, frame, now):
        try:
            held = shop.read_cargo_items(frame)
        except Exception as exc:
            self.state.note = f"读货舱失败：{exc}"
            return
        plan = []
        try:
            plan = advice_module.sell_plan(held, self.ledger, self.travel,
                                           now=now, current_map=self.state.map)
        except Exception:
            plan = []
        lines = []
        for item in plan:
            hops = item.get("hops")
            lines.append(f"{item['good']} → {item['merchant']}({item['map']}) "
                         f"@{item['price']}（{hops} 张图）")
        self.state.cargo = lines or (["（没有可信收购价，先去附近看看）"] if held else [])
        self.state.version += 1

    def _read_board(self, now):
        board = []
        try:
            observations = self.ledger.load()
        except Exception:
            observations = []
        latest = {}
        for observation in observations:
            key = observation.get("merchant") or observation.get("map")
            if not key:
                continue
            if key not in latest or observation.get("t", 0) > latest[key].get("t", 0):
                latest[key] = observation
        for key, observation in sorted(latest.items()):
            until = self.ledger.valid_until(observation)
            board.append({"merchant": key, "map": observation.get("map", ""),
                          "until": until,
                          "rows": observation.get("rows", [])})
        self.state.board = board
        self.state.version += 1


def _safe(function, frame, default=None):
    try:
        return function(frame)
    except Exception:
        return default


def _name(good_id):
    try:
        return shop.load_goods().get(good_id, {}).get("name", good_id)
    except Exception:
        return good_id


# ---------------------------------------------------------------------- GUI
def run_gui(interval=0.1):
    import tkinter as tk

    controller = Controller()
    root = tk.Tk()
    root.title("跑商助手")
    root.geometry("380x620")
    root.attributes("-topmost", True)

    tk.Label(root, text="当前建议", anchor="w", font=("Microsoft YaHei", 10, "bold")).pack(fill="x")
    advice_box = tk.Text(root, height=8, width=46, font=("Microsoft YaHei", 9))
    advice_box.pack(fill="x", padx=4)

    tk.Label(root, text="商人看板（货 + 倒计时）", anchor="w",
             font=("Microsoft YaHei", 10, "bold")).pack(fill="x")
    board_box = tk.Text(root, height=20, width=46, font=("Microsoft YaHei", 9))
    board_box.pack(fill="both", expand=True, padx=4)

    status = tk.Label(root, text="", anchor="w", font=("Microsoft YaHei", 8), fg="#666")
    status.pack(fill="x")

    worker = _Worker(_grabber(), controller, interval=interval)
    painted = {"version": -1, "at": 0.0}

    def paint(state):
        advice_box.delete("1.0", "end")
        advice_box.insert("end", "\n".join(state.advice) or "（打开商人界面后显示）")
        board_box.delete("1.0", "end")
        now = time.monotonic()
        for item in state.board:
            left = item["until"] - now
            if left > 0:
                mark = "●" if left > 60 else "◐"
                head = f"{mark} {item['merchant']}@{item['map']}　剩 {int(left)}s"
            else:
                head = f"○ {item['merchant']}@{item['map']}　已过期"
            board_box.insert("end", head + "\n")
            for row in item.get("rows", []):
                tag = "卖" if row.get("side") == "sell" else "收"
                board_box.insert("end", f"    {row.get('good','')} {tag} {row.get('price',0)}\n")
        status.config(text=f"{state.map or '(未知地图)'}　{state.note}")

    def tick():
        now = time.monotonic()
        try:
            state = worker.latest()
        except Exception as exc:
            status.config(text=f"读取失败：{exc}")
            root.after(int(interval * 1000), tick)
            return
        if state is None:
            root.after(int(interval * 1000), tick)
            return
        if (state.version != painted["version"] or now - painted["at"] >= REPAINT_EVERY
                or state.board):
            paint(state)
            painted["version"] = state.version
            painted["at"] = now
        root.after(int(interval * 1000), tick)

    root.after(0, tick)
    root.mainloop()


class _Worker:
    """后台线程：抓帧 + 全部识别/计算，UI 线程只取结果去画。"""

    def __init__(self, grab, controller, interval=0.1):
        import threading

        self._grab = grab
        self._controller = controller
        self._interval = interval
        self._lock = threading.Lock()
        self._state = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                frame = self._grab()
                if frame is not None:
                    state = self._controller.update(frame)
                    with self._lock:
                        self._state = state
            except Exception:
                pass
            self._stop.wait(self._interval)

    def latest(self):
        with self._lock:
            return self._state

    def stop(self):
        self._stop.set()


class _Capture:
    """后台线程抓帧：UI 线程只取最新一帧，拖动窗口时不会被抓帧卡住。"""

    def __init__(self, grab, interval=0.1):
        import queue
        import threading

        self._grab = grab
        self._interval = interval
        self._queue = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                frame = self._grab()
            except Exception:
                frame = None
            if frame is not None:
                try:
                    self._queue.get_nowait()      # 丢掉旧帧，永远只处理最新的
                except Exception:
                    pass
                try:
                    self._queue.put_nowait(frame)
                except Exception:
                    pass
            self._stop.wait(self._interval)

    def latest(self):
        try:
            return self._queue.get_nowait()
        except Exception:
            return None

    def stop(self):
        self._stop.set()


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
            return __import__("numpy").array(
                sct.grab({"left": ox, "top": oy, "width": cw, "height": ch}))[:, :, :3].copy()

    return grab


if __name__ == "__main__":
    run_gui()
