"""DeepSeek 客户端封装（OpenAI 兼容协议）。

- Key 仅从环境变量/`.env` 读取，绝不写死在代码里。
- 调用方负责解析返回文本（保持简单，不强制 json mode）。
"""
from __future__ import annotations

import os

from openai import OpenAI


class DeepSeekClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
        self._client: OpenAI | None = None

    def _ensure(self) -> None:
        if self._client is None:
            if not self.api_key:
                raise RuntimeError(
                    "未配置 DEEPSEEK_API_KEY。请在 config/.env 中填写（参考 config/.env.example）。"
                )
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def complete(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1500,
    ) -> str:
        self._ensure()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""

    def available(self) -> bool:
        return bool(self.api_key)
