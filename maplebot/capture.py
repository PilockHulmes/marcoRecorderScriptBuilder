"""截屏线程 + 小地图识别（唯一实现）。

原来有两份几乎相同的拷贝：

- `haikuScripts/capture.py`：窗口标题从 `maplebot.local.json` 读，可传窗口名，
  带 `@bot` 验证码模板检测，符文 / 黑屏 / 符文 buff 检测全被注释掉。
- `auto-maple/src/capture.py`：窗口标题同上，符文 / 黑屏 / 符文 buff 检测是开的。

合并后这些差异全部变成构造参数，两个薄壳各自选择默认值（行为保持不变）：

.. code-block:: python

    # haikuScripts/capture.py
    Capture(window_name=settings.window_title(), assets_dir=<haikuScripts/assets>)

    # auto-maple/src/capture.py
    Capture(window_name=settings.window_title(), assets_dir=<auto-maple/assets>,
            detect_rune=True, detect_blackscreen=True, detect_rune_buff=True)

模板改为**按需加载**：只有开着对应检测才要求对应模板存在，缺文件会给出
明确的可执行错误（而不是 `NoneType has no attribute shape`）。
"""

import threading
import time
from pathlib import Path

import cv2
import mss
import mss.windows
import numpy as np

from . import config, settings, utils, win32
from . import minimap as minimap_mod
from . import player as player_mod

# 小地图边框：上边距 5px，其余三边 9px（标定用）
MINIMAP_TOP_BORDER = 5
MINIMAP_BOTTOM_BORDER = 9

# 窗口模式下窗口客户区相对窗口左上角的偏移（历史值，当前未使用，保留给调参）
WINDOWED_OFFSET_TOP = 36
WINDOWED_OFFSET_LEFT = 10

# 客户端默认标题；不同客户端版本不一致，用参数覆盖或 run.py --window 覆盖
DEFAULT_WINDOW_NAME = settings.window_title()

# 小地图上符文的颜色范围（HSV）
RUNE_RANGES = (
    ((141, 148, 245), (146, 158, 255)),
)

# 小地图上其他玩家的颜色范围（HSV）
OTHER_RANGES = (
    ((0, 245, 215), (10, 255, 255)),
)

# 必需模板（灰度读取）
REQUIRED_TEMPLATES = {
    "minimap_tl": "minimap_tl_template.png",
    "minimap_br": "minimap_br_template.png",
    "player": "player_template.png",
}

# 需要先做 HSV 过滤再转灰度的模板（可选：只有对应检测打开时才需要）
OPTIONAL_COLOR_TEMPLATES = {
    "other": ("other_template.png", OTHER_RANGES),
    "rune": ("rune_template.png", RUNE_RANGES),
}

# 可选模板（灰度读取），只在开启对应检测时才需要
OPTIONAL_TEMPLATES = {
    "rune_buff": "rune_buff_template.jpg",
    "bot_testing_tl": "haiku_bot_testing_tl_template.jpg",
    "bot_testing_br": "haiku_bot_testing_br_template.jpg",
}


def load_templates(assets_dir):
    """从 ASSETS_DIR 读取模板，返回 dict。

    必需模板缺失、或图片读不出来时抛 :class:`FileNotFoundError`，
    错误信息里带上绝对路径和当前工作目录，方便排查。
    """
    base = Path(assets_dir).expanduser()
    if not base.is_absolute():
        base = Path.cwd() / base
    if not base.is_dir():
        raise FileNotFoundError(
            f"素材目录不存在：{base}（当前工作目录 {Path.cwd()}）"
        )

    tpl = {}

    def read_gray(name, filename):
        path = base / filename
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise FileNotFoundError(f"模板读取失败：{path}")
        tpl[name] = img

    for name, filename in REQUIRED_TEMPLATES.items():
        read_gray(name, filename)

    for name, (filename, ranges) in OPTIONAL_COLOR_TEMPLATES.items():
        img = cv2.imread(str(base / filename))
        if img is not None:
            tpl[name] = cv2.cvtColor(utils.filter_color(img, ranges), cv2.COLOR_BGR2GRAY)

    for name, filename in OPTIONAL_TEMPLATES.items():
        img = cv2.imread(str(base / filename), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            tpl[name] = img

    tpl["minimap_hw"] = (
        max(tpl["minimap_tl"].shape[0], tpl["minimap_br"].shape[0]),
        max(tpl["minimap_tl"].shape[1], tpl["minimap_br"].shape[1]),
    )
    tpl["player_hw"] = tpl["player"].shape
    return tpl


class Capture:
    """后台线程持续截图，把角色位置等信息写进 :mod:`maplebot.config`。

    参数（默认值等于 `auto-maple` 那份实现；`haikuScripts` 的薄壳会覆盖其中几项）：

    :param window_name:       窗口标题，精确匹配。
    :param assets_dir:        模板所在目录，可为相对路径（相对当前工作目录）。
    :param detect_other:      是否在小地图上找其他玩家。`haikuScripts` 已把这件事
                              交给 ``botCheckSolver.hasPplInMap()``（顺便存档截图），
                              所以那边关掉；`auto-maple` 仍然开着。
    :param detect_rune:       是否在小地图上找符文（auto-maple 开着）。
    :param detect_blackscreen:是否做黑屏检测（auto-maple 开着）。
    :param detect_rune_buff:  是否检测符文 buff 图标（auto-maple 开着）。
    :param detect_bot_testing:是否检测 `@bot` 验证码弹窗（haikuScripts 有模板）。
    :param frame_interval:    两次截图之间的间隔（秒）；haikuScripts 用 0.1，auto-maple 用 0.05。
    :param minimap_locator:   小地图定位方式：``"auto"``（先找白色圆角边框，找不到再退回模板）、
                              ``"white_border"``、``"template"``（旧行为）。
                              客户端改版后旧角模板失效，默认 ``auto``。
    """

    def __init__(
        self,
        window_name=DEFAULT_WINDOW_NAME,
        assets_dir="assets",
        *,
        detect_other=True,
        detect_rune=False,
        detect_blackscreen=False,
        detect_rune_buff=False,
        detect_bot_testing=False,
        frame_interval=0.1,
        minimap_locator="auto",
    ):
        config.capture = self

        self.tpl = load_templates(assets_dir)
        self.assets_dir = str(assets_dir)
        self.window_name = config.window_override or window_name
        self.frame_interval = float(frame_interval)
        if minimap_locator not in ("auto", "white_border", "template"):
            raise ValueError(f"未知的 minimap_locator：{minimap_locator!r}")
        self.minimap_locator = minimap_locator
        self.minimap_source = None
        #: 小地图内容区 (x, y, w, h)，标定后才有值
        self.minimap_content = None
        #: 角色位置跟踪器（颜色识别 + 连续性 + 平滑 + 丢失标记）
        self.player_tracker = player_mod.PlayerTracker()

        self.detect_other = bool(detect_other) and "other" in self.tpl
        self.detect_rune = bool(detect_rune) and "rune" in self.tpl
        self.detect_blackscreen = bool(detect_blackscreen)
        self.detect_rune_buff = bool(detect_rune_buff) and "rune_buff" in self.tpl
        self.detect_bot_testing = (
            bool(detect_bot_testing) and "bot_testing_tl" in self.tpl and "bot_testing_br" in self.tpl
        )
        for label, requested, resolved, missing in (
            ("detect_other", detect_other, self.detect_other, "other"),
            ("detect_rune", detect_rune, self.detect_rune, "rune"),
            ("detect_rune_buff", detect_rune_buff, self.detect_rune_buff, "rune_buff"),
            ("detect_bot_testing", detect_bot_testing, self.detect_bot_testing, "bot_testing_*"),
        ):
            if requested and not resolved:
                print(f"[capture] 缺少 {missing} 模板，已关闭 {label}")

        self.window = {"left": 0, "top": 0, "width": 1366, "height": 768}
        self.minimap_ratio = 1
        self.minimap_sample = None
        self.calibrated = False
        self.screenshoter = None
        self.thread = threading.Thread(target=self._main)
        self.thread.daemon = True
        self.minimap_topleft_position = None
        self.minimap_bottomright_position = None
        self.haiku_bot_testing_topleft_position = None
        self.haiku_bot_testing_bottomright_position = None
        # cv2 BGR 格式的整窗截图
        self.frame = None
        self._last_missing_warning = 0.0

    # ------------------------------------------------------------------ 线程
    def start(self):
        print(f"Start the video capture (window={self.window_name!r}, assets={self.assets_dir!r})")
        self.thread.start()

    def set_frame_interval(self, seconds):
        """运行期调整截屏间隔（秒），下一帧生效。

        脚本在「等技能 CD / 等落地」这类不需要高频定位的阶段可以调大（例如 0.3~1.0），
        需要精细定位时再调回来，省 CPU 的同时不影响动作精度。
        """
        seconds = float(seconds)
        if seconds <= 0:
            raise ValueError("frame_interval 必须大于 0")
        self.frame_interval = seconds
        return seconds

    def _main(self):
        mss.windows.CAPTUREBLT = 0
        while True:
            with mss.mss() as self.screenshoter:
                # 窗口还没就绪就等，别把垃圾矩形当成标定结果
                while not self.calibrate():
                    time.sleep(1.0)
                while True:
                    if not self.calibrated:
                        print("not calibrated properly, redo it")
                        break

                    # Take screenshot
                    self.frame = self.screenshot()
                    if self.frame is None:
                        continue

                    # Crop the frame to only show the minimap
                    minimap = self.frame[
                        self.minimap_topleft_position[1]:self.minimap_bottomright_position[1],
                        self.minimap_topleft_position[0]:self.minimap_bottomright_position[0],
                    ]
                    config.minimap = minimap

                    # Determine the player's position
                    self._update_player()

                    # 符文位置（haikuScripts 默认关闭，auto-maple 开启）
                    if self.detect_rune:
                        filtered = utils.filter_color(minimap, RUNE_RANGES)
                        rune = utils.multi_match(filtered, self.tpl["rune"], threshold=0.9)
                        if rune:
                            config.rune_position = utils.convert_to_relative(rune[0], minimap)
                            config.rune_active = True
                        # 没找到时不做处理：清除由符文求解器负责

                    # 其他玩家（haikuScripts 关掉：改由 botCheckSolver.hasPplInMap() 负责）
                    if self.detect_other:
                        filtered = utils.filter_color(minimap, OTHER_RANGES)
                        others_count = len(utils.multi_match(filtered, self.tpl["other"], threshold=0.5))
                        config.map_invaded = others_count > 0

                    # 黑屏检测（掉线/换图）
                    if self.detect_blackscreen:
                        gray = cv2.cvtColor(self.frame, cv2.COLOR_BGR2GRAY)
                        height, width, _ = self.frame.shape
                        room_change_threshold = 0.9
                        config.blackscreened = (
                            np.count_nonzero(gray < 15) / height / width > room_change_threshold
                        )

                    # 符文 buff 图标（用来取消 buff）
                    if self.detect_rune_buff:
                        rune_buff = utils.multi_match(
                            self.frame[: self.frame.shape[0] // 8, :],
                            self.tpl["rune_buff"],
                            threshold=0.9,
                        )
                        if rune_buff:
                            position_in_name = min(rune_buff, key=lambda p: p[0])
                            config.rune_buff_position = (
                                position_in_name[0] + self.window["left"],
                                position_in_name[1] + self.window["top"],
                            )
                        else:
                            config.rune_buff_position = None

                    # @bot 验证码弹窗
                    if self.detect_bot_testing:
                        self.botTestingDetection()
                        if (
                            self.haiku_bot_testing_bottomright_position is not None
                            or self.haiku_bot_testing_topleft_position is not None
                        ):
                            config.bottesting = True

                    time.sleep(self.frame_interval)

    # ------------------------------------------------------------------ 工具
    def _update_player(self):
        """把当前帧的角色位置写进 ``config``（每帧调用，也可单独测试）。

        - 定位成功：写平滑后的归一化坐标，``player_stale=False``；
        - 跟踪丢失（被遮挡/切图）：**保持上一次的值**，不写 ``(0, 0)``，只把
          ``player_stale`` 置 True；
        - 从来没定位到：保持 ``(0, 0)``，``player_stale=True``。
        """
        rect = self.minimap_content
        if rect is None or self.frame is None:
            config.player_stale = True
            return None

        position = self.player_tracker.update(self.frame, rect)
        config.player_stale = self.player_tracker.stale or position is None
        if position is None:
            return None

        x0, y0, width, _height = rect
        # 与 utils.convert_to_relative 一致：两个轴都除以宽度，保证各向同性
        config.player_position = ((position[0] - x0) / width, (position[1] - y0) / width)
        raw = self.player_tracker.raw
        config.player_score = float(raw.score) if raw is not None else 0.0
        return config.player_position

    def collectFrames(self, count=10, interval=0.1):
        with mss.mss() as screenshoter:
            result = [np.array(screenshoter.grab(self.window))]
            for _ in range(count):
                time.sleep(interval)
                result.append(np.array(screenshoter.grab(self.window)))
            return result

    def calibrate(self):
        """定位窗口并算出小地图矩形。成功返回 True；窗口没就绪返回 False。"""
        handle = win32.find_window(self.window_name)
        if not handle:
            self.calibrated = False
            now = time.monotonic()
            if now - self._last_missing_warning > 10:
                self._last_missing_warning = now
                print(
                    f"[capture] 找不到窗口 {self.window_name!r}，继续等待……"
                    f"（标题必须精确匹配，可用 run.py --window 覆盖）"
                )
            return False

        rect = win32.window_rect(handle)
        if rect is None:
            self.calibrated = False
            return False
        left, top, right, bottom = rect

        self.window["left"] = left
        self.window["top"] = top
        self.window["width"] = max(right - left, self.tpl["minimap_hw"][1])
        self.window["height"] = max(bottom - top, self.tpl["minimap_hw"][0])

        # 定位小地图：新版客户端用「白色圆角边框」，老版回退到角模板
        self.frame = self.screenshot()
        if self.frame is None:
            self.calibrated = False
            return False

        box = None
        if self.minimap_locator in ("auto", "white_border"):
            box = minimap_mod.find_minimap(self.frame)

        if box is not None:
            inner = box.inner()
            self.minimap_topleft_position = (inner.x, inner.y)
            self.minimap_bottomright_position = (inner.right, inner.bottom)
            source = "white_border"
        elif self.minimap_locator in ("auto", "template"):
            tl, _ = utils.single_match(self.frame, self.tpl["minimap_tl"])
            _, br = utils.single_match(self.frame, self.tpl["minimap_br"])
            self.minimap_topleft_position = (
                tl[0] + MINIMAP_BOTTOM_BORDER,
                tl[1] + MINIMAP_TOP_BORDER,
            )
            self.minimap_bottomright_position = (
                max(self.minimap_topleft_position[0] + self.tpl["player_hw"][1],
                    br[0] - MINIMAP_BOTTOM_BORDER),
                max(self.minimap_topleft_position[1] + self.tpl["player_hw"][0],
                    br[1] - MINIMAP_BOTTOM_BORDER),
            )
            source = "template"
        else:
            self.calibrated = False
            return False

        if source != self.minimap_source:
            print(f"[capture] 小地图定位方式：{source} "
                  f"{self.minimap_topleft_position}..{self.minimap_bottomright_position}")
            self.minimap_source = source

        self.minimap_content = (
            self.minimap_topleft_position[0],
            self.minimap_topleft_position[1],
            self.minimap_bottomright_position[0] - self.minimap_topleft_position[0],
            self.minimap_bottomright_position[1] - self.minimap_topleft_position[1],
        )
        # 重新标定 = 可能换了地图/窗口，跟踪轨迹作废
        self.player_tracker.reset()

        self.minimap_ratio = (
            (self.minimap_bottomright_position[0] - self.minimap_topleft_position[0])
            / (self.minimap_bottomright_position[1] - self.minimap_topleft_position[1])
        )
        self.minimap_sample = self.frame[
            self.minimap_topleft_position[1]:self.minimap_bottomright_position[1],
            self.minimap_topleft_position[0]:self.minimap_bottomright_position[0],
        ]
        self.calibrated = True
        return True

    def screenshot(self, delay=1):
        try:
            return np.array(self.screenshoter.grab(self.window))
        except mss.exception.ScreenShotError:
            print(
                f"\n[!] Error while taking screenshot, retrying in {delay} second"
                + ("s" if delay != 1 else "")
            )
            time.sleep(delay)

    def botTestingDetection(self):
        """找 `@bot` 验证码弹窗的左上/右下角。需要先校准。"""
        if self.frame is None:
            return
        tl, _ = utils.single_match(self.frame, self.tpl["bot_testing_tl"])
        _, br = utils.single_match(self.frame, self.tpl["bot_testing_br"])
        self.haiku_bot_testing_topleft_position = (tl[0], tl[1])
        self.haiku_bot_testing_bottomright_position = (br[0], br[1])
