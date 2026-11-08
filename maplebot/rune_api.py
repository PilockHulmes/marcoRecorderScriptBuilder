"""DeepSeek 视觉 API 的最小封装：一张箭头小图 → 4 个方向。

只负责"问"和"解析"，不做任何时机决策、重试策略、按键动作（那些在
:mod:`maplebot.rune` 和调用方）。

接入方式（官方文档指定，DeepSeek 没有自研 Python SDK）：

    from openai import OpenAI
    client = OpenAI(api_key=..., base_url="https://api.deepseek.com")
    client.chat.completions.create(model="deepseek-flash", messages=[...])

凭据来自仓库根目录的 ``deepseek.local.json``（已被 .gitignore 的 ``*.local.json`` 忽略）：

    {"api_key": "...", "base_url": "https://api.deepseek.com", "model": "deepseek-flash"}

也接受只写裸 key 的纯文本文件。
"""

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path

import cv2

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"
DEFAULT_CREDENTIALS_PATH = Path(__file__).resolve().parents[1] / "deepseek.local.json"

DIRECTIONS = ("up", "down", "left", "right")

SYSTEM_PROMPT = """You parse MapleStory rune puzzle screenshots.
The image contains exactly four direction arrows, arranged left to right.
Ignore surrounding text, monsters, damage numbers, mouse cursors and UI.
Answer with JSON only, no prose:
{"arrows": ["up" | "down" | "left" | "right", ... exactly 4 items, left to right]}
If you cannot see exactly four clearly readable arrows, answer:
{"arrows": [], "error": "<short reason>"}
Never guess a direction you cannot see."""

USER_PROMPT = "Read the four arrows from left to right and reply with the JSON."


class RuneConfigError(Exception):
    """凭据/依赖没准备好（不是识别失败）。"""


class RuneAPIError(Exception):
    """请求失败或响应不可用。"""


class RuneSolveError(RuneAPIError):
    """拿到了响应，但解析不出 4 个合法方向（调用方应当作"不确定"处理）。"""


@dataclass
class Credentials:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL


# ---------------------------------------------------------------- 凭据
def load_credentials(path=None):
    """读取凭据文件；支持 JSON 或裸 key 纯文本（允许 UTF-8 BOM）。"""
    path = Path(path) if path is not None else DEFAULT_CREDENTIALS_PATH
    if not path.is_file():
        raise RuneConfigError(
            f"找不到密钥文件：{path}\n"
            f"请在仓库根创建 deepseek.local.json，内容形如 "
            f'{{"api_key": "sk-...", "base_url": "{DEFAULT_BASE_URL}", "model": "{DEFAULT_MODEL}"}}'
        )

    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        raise RuneConfigError(f"密钥文件是空的：{path}")

    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuneConfigError(f"密钥文件不是合法 JSON：{path}（{exc}）") from exc
        if not isinstance(data, dict):
            raise RuneConfigError(f"密钥文件顶层必须是对象：{path}")
        api_key = str(data.get("api_key") or "").strip()
        base_url = str(data.get("base_url") or DEFAULT_BASE_URL).strip()
        model = str(data.get("model") or DEFAULT_MODEL).strip()
    else:
        # 只贴了一个裸 key
        api_key = text.splitlines()[0].strip()
        base_url = DEFAULT_BASE_URL
        model = DEFAULT_MODEL

    if not api_key:
        raise RuneConfigError(f"密钥文件里 api_key 是空的：{path}")
    return Credentials(api_key=api_key, base_url=base_url, model=model)


# ---------------------------------------------------------------- 图片编码
def encode_png(image_bgr):
    """BGR ndarray → PNG bytes。

    注意：``cv2.imencode`` 写出的 PNG 颜色是正确的（不需要手动 BGR→RGB），
    已用纯红图 + PIL 读回验证过。
    """
    if image_bgr is None or getattr(image_bgr, "size", 0) == 0:
        raise ValueError("待编码的图片为空")
    ok, buffer = cv2.imencode(".png", image_bgr)
    if not ok:
        raise ValueError("PNG 编码失败")
    return buffer.tobytes()


def to_data_url(png_bytes):
    """PNG bytes → ``data:image/png;base64,...``（每张图 ≤1024 token）。"""
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")


# ---------------------------------------------------------------- 解析
_ALIASES = {
    "up": "up", "down": "down", "left": "left", "right": "right",
    "上": "up", "下": "down", "左": "left", "右": "right",
    "↑": "up", "↓": "down", "←": "left", "→": "right",
}


def _extract_json(text):
    """从模型输出里抠出 JSON：兼容 ```json 围栏、前后废话、裸数组。"""
    body = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", body, re.S)
    if fence:
        body = fence.group(1).strip()

    try:
        return json.loads(body)
    except json.JSONDecodeError:
        pass

    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = body.find(opener), body.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(body[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise RuneSolveError(f"响应里没有合法 JSON；原文：{text[:200]!r}")


def parse_arrows(content):
    """把模型回复解析成 4 个方向；任何不对劲都抛 :class:`RuneSolveError`。"""
    if content is None or not str(content).strip():
        raise RuneSolveError("模型返回空内容（可能被 JSON Output 过滤成空白）")

    data = _extract_json(str(content))
    if isinstance(data, dict):
        raw = data.get("arrows", data.get("directions"))
        error = data.get("error")
        if (raw is None or raw == []) and error:
            raise RuneSolveError(f"模型表示看不清：{error}")
    elif isinstance(data, list):
        raw = data
    else:
        raw = None
    if not isinstance(raw, list):
        raise RuneSolveError(f"响应缺少 arrows 数组；原文：{str(content)[:200]!r}")

    arrows = []
    for item in raw:
        key = str(item).strip().lower()
        arrows.append(_ALIASES.get(key, key))

    if len(arrows) != 4:
        raise RuneSolveError(f"箭头数量不是 4（收到 {len(arrows)} 个）：{arrows}")
    bad = [a for a in arrows if a not in DIRECTIONS]
    if bad:
        raise RuneSolveError(f"出现非法方向：{bad}（全部：{arrows}）")
    return arrows


# ---------------------------------------------------------------- 客户端
class RuneSolver:
    """把一张箭头小图发给 DeepSeek，读回 4 个方向。

    :param credentials: 不给就用 :func:`load_credentials` 读本地文件。
    :param client:      测试用，注入假的 OpenAI 兼容客户端。
    :param timeout:     单次请求超时（秒）。
    """

    def __init__(self, credentials=None, client=None, timeout=20.0):
        self.credentials = credentials or load_credentials()
        self.timeout = float(timeout)
        self._client = client
        self.last_payload = None

    @property
    def client(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - 依赖缺失
                raise RuneConfigError("未安装 openai，请先 pip install openai") from exc
            self._client = OpenAI(
                api_key=self.credentials.api_key,
                base_url=self.credentials.base_url or None,
                timeout=self.timeout,
                max_retries=1,
            )
        return self._client

    def build_request(self, data_url):
        """构造 chat.completions.create 的参数（单独成方法，方便测试/调试）。"""
        return {
            "model": self.credentials.model,
            "temperature": 0,
            "max_tokens": 200,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": USER_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
                    ],
                },
            ],
            # 纯提取任务，不需要思考模式；放在 extra_body 里透传给 API
            "extra_body": {"thinking": {"type": "disabled"}},
        }

    def solve(self, image_bgr):
        """返回 4 个方向（左→右）。失败抛 :class:`RuneAPIError` 子类。"""
        data_url = to_data_url(encode_png(image_bgr))
        payload = self.build_request(data_url)
        self.last_payload = payload
        try:
            response = self.client.chat.completions.create(**payload)
        except Exception as exc:  # 网络/鉴权/限流都在这里
            raise RuneAPIError(f"请求 DeepSeek 失败：{type(exc).__name__}: {exc}") from exc

        try:
            content = response.choices[0].message.content
        except Exception as exc:
            raise RuneAPIError(f"响应结构异常：{exc}") from exc
        return parse_arrows(content)


__all__ = [
    "Credentials",
    "DEFAULT_BASE_URL",
    "DEFAULT_CREDENTIALS_PATH",
    "DEFAULT_MODEL",
    "DIRECTIONS",
    "RuneAPIError",
    "RuneConfigError",
    "RuneSolveError",
    "RuneSolver",
    "encode_png",
    "load_credentials",
    "parse_arrows",
    "to_data_url",
]
