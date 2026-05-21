"""OpenRouter provider — access 200+ models through one API key."""

from __future__ import annotations

from typing import Any

from hive.config import get_env
from hive.models.openai import OpenAI


class OpenRouter(OpenAI):
    """OpenRouter provider for multi-provider model access."""

    def __init__(
        self,
        model: str = "deepseek/deepseek-v4-flash",
        api_key: str | None = None,
    ):
        key = api_key or get_env("OPENROUTER_API_KEY")
        super().__init__(
            model=model,
            api_key=key or "not-set",
            base_url="https://openrouter.ai/api/v1",
        )
        self._has_key = bool(key)

    @classmethod
    def lite(cls, **kwargs: Any) -> OpenRouter:
        """DeepSeek V4 Flash — fast and cheap."""
        return cls(model="deepseek/deepseek-v4-flash", **kwargs)

    @classmethod
    def standard(cls, **kwargs: Any) -> OpenRouter:
        """Moonshot Kimi — balanced."""
        return cls(model="moonshotai/kimi-latest", **kwargs)

    @classmethod
    def pro(cls, **kwargs: Any) -> OpenRouter:
        """Anthropic Claude Sonnet — most capable."""
        return cls(model="anthropic/claude-sonnet-latest", **kwargs)
