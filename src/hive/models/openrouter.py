"""OpenRouter provider — access 200+ models through one API key."""

from __future__ import annotations

from typing import Any

from hive.config import get_env
from hive.models.openai import OpenAI


class OpenRouter(OpenAI):
    """OpenRouter provider for multi-provider model access."""

    def __init__(
        self,
        model: str = "anthropic/claude-sonnet-4-6",
        api_key: str | None = None,
    ):
        key = api_key or get_env("OPENROUTER_API_KEY") or None
        super().__init__(
            model=model,
            api_key=key,
            base_url="https://openrouter.ai/api/v1",
        )

    @classmethod
    def lite(cls, **kwargs: Any) -> OpenRouter:
        """DeepSeek V4 Flash — fast and cheap."""
        return cls(model="deepseek/deepseek-v4-flash", **kwargs)

    @classmethod
    def standard(cls, **kwargs: Any) -> OpenRouter:
        """Moonshot Kimi K2.6 — balanced."""
        return cls(model="moonshotai/kimi-k2.6", **kwargs)

    @classmethod
    def pro(cls, **kwargs: Any) -> OpenRouter:
        """Google Gemini 2.5 Pro — most capable."""
        return cls(model="google/gemini-2.5-pro", **kwargs)
