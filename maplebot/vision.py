"""通用的「图片 + 问题 → 文字」调用（给验证码、符文等共用）。

和 :mod:`maplebot.rune_api` 用的是同一个 DeepSeek 视觉模型，只是提示词不同：
符文要 4 个方向，验证码要一串字符。
"""

from . import rune_api


class VisionClient:
    """薄封装：只负责"发一张图 + 两段提示词，拿回文本"。"""

    def __init__(self, credentials=None, client=None, timeout=20.0):
        self.credentials = credentials or rune_api.load_credentials()
        self.timeout = float(timeout)
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.credentials.api_key,
                base_url=self.credentials.base_url or None,
                timeout=self.timeout,
                max_retries=1,
            )
        return self._client

    def ask(self, image_bgr, system, user, max_tokens=60, detail="high"):
        """返回模型输出的原始文本；网络/接口错误抛 :class:`rune_api.RuneAPIError`。"""
        data_url = rune_api.to_data_url(rune_api.encode_png(image_bgr))
        try:
            response = self.client.chat.completions.create(
                model=self.credentials.model,
                temperature=0,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user},
                            {"type": "image_url", "image_url": {"url": data_url, "detail": detail}},
                        ],
                    },
                ],
                extra_body={"thinking": {"type": "disabled"}},
            )
        except Exception as exc:
            raise rune_api.RuneAPIError(f"请求 DeepSeek 失败：{type(exc).__name__}: {exc}") from exc
        try:
            return response.choices[0].message.content or ""
        except Exception as exc:
            raise rune_api.RuneAPIError(f"响应结构异常：{exc}") from exc
