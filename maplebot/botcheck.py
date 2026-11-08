"""挂机监测（bot check）：检测面板、取证、读验证码、输入、验收。

流程（和玩家群里的人做法一致）：

1. **检测**：屏幕上出现那块半透明蓝面板（三行固定文字 + 验证码 + 倒计时）；
2. **取证**：先截一张**游戏窗口整窗**图（证明人在看屏幕），发给 QQ 群；
3. **识别**：裁验证码框 → 视觉 API 连问 3 次，**三次完全一致才采用**；
4. **输入**：点击验证码框 → 逐字符输入（大小写用 shift）→ 回车；
5. **验收**：面板消失 = 成功；还在 = 失败（**不重复输入**，只报警）。

检测为什么双保险：

- 文字块模板匹配很便宜（每帧几 ms），同尺度截图实测 0.90~1.00；
- 但换分辨率 / 亮背景下会掉到 0.2~0.4，所以每隔几秒用 PaddleOCR 兜底
  （1000 px 宽时约 366 ms，能稳定认出「請按下ENTER鍵」）。
"""

import random
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from . import config, rune_api, utils, vision

ASSETS_DIR = Path(__file__).resolve().parents[1] / "haikuScripts" / "assets"

#: 面板上三行固定文字的模板（从真实截图裁的）
PANEL_TEMPLATE = "botcheck_text.png"
#: 模板命中阈值（同尺度实测 0.90~1.00）
PANEL_THRESHOLD = 0.80
#: 模板的尺度梯度（客户端分辨率可能不同）
PANEL_SCALES = (0.9, 1.0, 1.1)
#: 验证码框相对"文字块模板左上角"的偏移 (dx, dy, w, h)，实测
CAPTCHA_OFFSET = (-33, 70, 224, 60)

#: OCR 兜底：把画面缩到这个宽度再识别（1000 px 实测 366 ms 且稳定）
OCR_WIDTH = 1000
#: 面板文字里的固定关键词（繁简都认，OCR 可能把繁體认成简体）
PANEL_KEYWORDS = ("ENTER", "下方", "輸入", "输入")

#: 验证码提示词
CAPTCHA_SYSTEM = (
    "You read captcha images from a game. "
    "Output ONLY the visible characters, exactly as shown, preserving case. "
    "No quotes, no spaces, no explanation. "
    "If the image is unreadable, output exactly: UNKNOWN"
)
CAPTCHA_USER = "Read the characters in this captcha."

CAPTCHA_MIN_LEN, CAPTCHA_MAX_LEN = 3, 10
CAPTCHA_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

#: 模板里第一行「將下方圖片中的文字」的大致像素宽（用来估 OCR 命中时的缩放）
TPL_LINE1_WIDTH = 150.0
#: 如果 OCR 只认到第三行（ENTER），它相对文字块顶部的 y 偏移（按 1.0 尺度）
LINE3_OFFSET_Y = 42


@dataclass(frozen=True)
class BotCheckPanel:
    """检测到的监测面板。"""

    text_bbox: tuple      # 文字块 (x, y, w, h)
    captcha_bbox: tuple   # 验证码框 (x, y, w, h)
    score: float

    @property
    def center(self):
        x, y, w, h = self.captcha_bbox
        return x + w // 2, y + h // 2


def load_panel_template(assets_dir=None):
    path = Path(assets_dir or ASSETS_DIR) / PANEL_TEMPLATE
    gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise FileNotFoundError(f"监测面板模板读取失败：{path}")
    return gray


def _match_template(frame, template, scales):
    """多尺度模板匹配，返回 (最高分, (x, y, w, h), 命中尺度)。"""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    best = (0.0, None, None)
    for scale in scales:
        tpl = template
        if abs(scale - 1.0) > 0.01:
            tpl = cv2.resize(template, None, fx=scale, fy=scale,
                             interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        if tpl.shape[0] > gray.shape[0] or tpl.shape[1] > gray.shape[1]:
            continue
        result = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val > best[0]:
            best = (float(max_val), (max_loc[0], max_loc[1], tpl.shape[1], tpl.shape[0]), scale)
    return best


def find_panel(frame, assets_dir=None, threshold=PANEL_THRESHOLD):
    """用模板找面板；返回 :class:`BotCheckPanel` 或 None。"""
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    score, bbox, _scale = _match_template(frame, load_panel_template(assets_dir), PANEL_SCALES)
    if bbox is None or score < threshold:
        return None
    x, y, w, h = bbox
    dx, dy, cw, ch = CAPTCHA_OFFSET
    captcha = (
        max(0, x + dx),
        max(0, y + dy),
        min(cw, frame.shape[1] - max(0, x + dx)),
        min(ch, frame.shape[0] - max(0, y + dy)),
    )
    return BotCheckPanel(text_bbox=bbox, captcha_bbox=captcha, score=score)


def confirm_panel_with_ocr(frame, ocr=None, width=OCR_WIDTH):
    """OCR 兜底：在画面里找「請按下ENTER鍵」这类固定文字。

    :return: 命中的文本列表（空列表 = 没找到）
    """
    texts = _ocr_texts(frame, ocr, width)
    return [text for text in texts if any(key in text.upper() for key in PANEL_KEYWORDS)]


def _ocr_texts(frame, ocr=None, width=OCR_WIDTH):
    return [text for text, _box in _ocr_lines(frame, ocr, width)]


def _ocr_lines(frame, ocr=None, width=OCR_WIDTH):
    """OCR 并返回 ``[(text, (x0, y0, x1, y1))]``，坐标已换算回原图。"""
    if frame is None or getattr(frame, "size", 0) == 0:
        return []
    if ocr is None:
        import logging

        from paddleocr import PaddleOCR

        logging.getLogger("ppocr").setLevel(logging.ERROR)
        ocr = PaddleOCR(lang="ch", show_log=False)
    height, w = frame.shape[:2]
    image = frame
    scale = 1.0
    if w > width:
        scale = width / w
        image = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    result = ocr.ocr(image)
    lines = []
    if result and result[0]:
        for line in result[0]:
            try:
                text = str(line[1][0])
                box = np.array(line[0], dtype=np.float32)
                x0, y0 = box.min(axis=0) / scale
                x1, y1 = box.max(axis=0) / scale
                lines.append((text, (float(x0), float(y0), float(x1), float(y1))))
            except Exception:
                continue
    return lines


def find_panel_ocr(frame, ocr=None, width=OCR_WIDTH):
    """OCR 兜底建面板：用固定文字行的位置 + 缩放，反推文字块和验证码框。"""
    for text, (x0, y0, x1, y1) in _ocr_lines(frame, ocr, width):
        upper = text.upper()
        is_line1 = "下方" in text
        if not is_line1 and "ENTER" not in upper:
            continue
        line_width = x1 - x0
        scale = line_width / TPL_LINE1_WIDTH if line_width > 10 else 1.0
        origin_x = x0
        origin_y = y0 if is_line1 else y0 - LINE3_OFFSET_Y * scale
        dx, dy, cw, ch = CAPTCHA_OFFSET
        text_bbox = (int(origin_x), int(origin_y), int(156 * scale), int(64 * scale))
        captcha_bbox = (
            max(0, int(origin_x + dx * scale)),
            max(0, int(origin_y + dy * scale)),
            int(cw * scale),
            int(ch * scale),
        )
        return BotCheckPanel(text_bbox=text_bbox, captcha_bbox=captcha_bbox, score=0.0)
    return None


def find_panel_any(frame, ocr=None, verify=False, ocr_width=OCR_WIDTH):
    """先模板、再 OCR 兜底；返回 (panel | None, 来源)。

    模板命中时直接返回；模板没命中且 ``verify`` 为真时跑一次 OCR，
    OCR 也能反推出验证码框的位置（用文字行位置 + 缩放）。
    """
    panel = find_panel(frame)
    if panel is not None:
        return panel, "template"
    if not verify:
        return None, "none"
    panel = find_panel_ocr(frame, ocr=ocr, width=ocr_width)
    if panel is not None:
        return panel, "ocr"
    return None, "none"


def captcha_crop(frame, panel, upscale=3.0):
    """裁出验证码框并放大（发给视觉模型前用）。"""
    x, y, w, h = panel.captcha_bbox
    crop = frame[y:y + h, x:x + w]
    if crop.size == 0:
        raise ValueError("验证码区域为空")
    if upscale and abs(upscale - 1.0) > 0.01:
        crop = cv2.resize(crop, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    return crop


def clean_captcha(text):
    """清洗模型输出：去引号/空白，只保留字母数字；不合法返回 None。"""
    if not text:
        return None
    body = str(text).strip().strip('"').strip("'").replace(" ", "").replace("\n", "")
    if body.upper() == "UNKNOWN":
        return None
    if not body or any(ch not in CAPTCHA_CHARS for ch in body):
        return None
    if not (CAPTCHA_MIN_LEN <= len(body) <= CAPTCHA_MAX_LEN):
        return None
    return body


def read_captcha(crop, client=None, attempts=3):
    """连问 ``attempts`` 次，**全部一致才返回**，否则 None（宁可不答）。"""
    client = client or vision.VisionClient()
    answers = []
    for _ in range(max(1, attempts)):
        try:
            raw = client.ask(crop, CAPTCHA_SYSTEM, CAPTCHA_USER, max_tokens=20)
        except rune_api.RuneAPIError:
            return None                       # 网络/接口问题：宁可不答
        cleaned = clean_captcha(raw)
        if cleaned is None:
            return None
        answers.append(cleaned)
    if len(set(answers)) != 1:
        return None
    return answers[0]


def _default_key_api():
    import pydirectinput

    return pydirectinput


def type_text(text, key_api=None, sleep=None, hold=0.02, gap=0.06):
    """逐字符输入（大写用 shift），最后回车。"""
    from . import stop

    api = key_api if key_api is not None else _default_key_api()
    wait = sleep if sleep is not None else time.sleep
    for char in text:
        stop.check()
        if char.isalpha() and char.isupper():
            api.keyDown("shift")
            wait(hold)
            api.keyDown(char.lower())
            api.keyUp(char.lower())
            wait(hold)
            api.keyUp("shift")
        else:
            api.keyDown(char)
            api.keyUp(char)
        wait(gap)
    api.keyDown("enter")
    api.keyUp("enter")


@dataclass
class GuardResult:
    handled: bool
    reason: str
    captcha: str = ""
    evidence: str = ""
    panel_score: float = 0.0


class BotCheckGuard:
    """把「检测 → 取证 → 读取 → 输入 → 验收」串起来。

    所有外部动作都可注入，方便离线测试：

    :param capture_frame: ``() -> BGR ndarray``，默认读 ``config.capture.frame``
    :param send_evidence: ``(png_bytes) -> bool``，默认存本地文件
    :param click:         ``(x, y) -> None``，默认 pydirectinput 点击
    :param key_api:       pydirectinput 或假实现
    :param vision:        :class:`maplebot.vision.VisionClient` 或假实现
    :param attempts:      验证码"必须一致"的次数
    :param verify_timeout: 输入后等面板消失的时间（秒）
    """

    def __init__(
        self,
        capture_frame=None,
        send_evidence=None,
        click=None,
        key_api=None,
        vision_client=None,
        attempts=3,
        verify_timeout=3.0,
        sleep=None,
        save_dir=None,
        ocr=None,
    ):
        self._capture = capture_frame or (lambda: getattr(config.capture, "frame", None))
        self._send_evidence = send_evidence or self._save_evidence
        self._click = click or self._default_click
        self.key_api = key_api
        self.vision = vision_client
        self.attempts = max(1, int(attempts))
        self.verify_timeout = float(verify_timeout)
        self._sleep = sleep or time.sleep
        self.save_dir = Path(save_dir) if save_dir else Path.cwd() / "detections"
        self.ocr = ocr

    # ------------------------------------------------------------ 默认动作
    def _default_click(self):
        import pydirectinput

        return pydirectinput.click

    def _save_evidence(self, png):
        self.save_dir.mkdir(parents=True, exist_ok=True)
        path = self.save_dir / f"botcheck_{time.strftime('%Y%m%d_%H%M%S')}.png"
        path.write_bytes(png)
        print(f"[botcheck] 证据已保存：{path}")
        return True

    # ------------------------------------------------------------ 主流程
    def handle(self):
        """检测到面板就处理一次；返回 :class:`GuardResult`。"""
        frame = self._capture()
        panel, source = find_panel_any(frame, ocr=self.ocr, verify=True)
        if panel is None:
            return GuardResult(False, "no_panel")

        # 1) 取证：先发证据（哪怕后续输入失败，也有"人在"的凭据）
        png = rune_api.encode_png(frame)
        evidence_ok = bool(self._send_evidence(png))
        evidence = "ok" if evidence_ok else "failed"

        # 2) 读验证码：三次一致才用
        crop = captcha_crop(frame, panel)
        captcha = read_captcha(crop, client=self.vision, attempts=self.attempts)
        if captcha is None:
            return GuardResult(False, "captcha_uncertain", evidence=evidence,
                               panel_score=panel.score)

        # 3) 点击验证码框 → 输入 → 回车
        cx, cy = panel.center
        self._click(cx, cy)
        self._sleep(0.2)
        type_text(captcha, key_api=self.key_api, sleep=self._sleep)

        # 4) 验收：面板消失 = 成功（不重复输入）
        if self._wait_panel_gone(source):
            return GuardResult(True, "solved", captcha=captcha, evidence=evidence,
                               panel_score=panel.score)
        return GuardResult(False, "still_there", captcha=captcha, evidence=evidence,
                           panel_score=panel.score)

    def _wait_panel_gone(self, source="template"):
        deadline = time.monotonic() + self.verify_timeout
        while True:
            frame = self._capture()
            present = find_panel(frame) is not None
            if not present and source == "ocr":
                present = find_panel_ocr(frame, ocr=self.ocr) is not None
            if not present:
                return True
            if time.monotonic() >= deadline:
                return False
            self._sleep(0.25)


__all__ = [
    "BotCheckGuard",
    "BotCheckPanel",
    "CAPTCHA_OFFSET",
    "GuardResult",
    "captcha_crop",
    "clean_captcha",
    "confirm_panel_with_ocr",
    "find_panel",
    "find_panel_any",
    "load_panel_template",
    "read_captcha",
    "type_text",
]
