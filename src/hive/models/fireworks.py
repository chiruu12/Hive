"""Fireworks provider — diverse open models."""

from __future__ import annotations

from typing import Any

from hive.models.openai import OpenAI


class Fireworks(OpenAI):
    """Fireworks AI provider for open models."""

    def __init__(
        self,
        model: str = "accounts/fireworks/models/deepseek-v4-pro",
        api_key: str | None = None,
    ):
        from hive.config import get_env

        key = api_key or get_env("FIREWORKS_API_KEY") or None
        super().__init__(
            model=model,
            api_key=key,
            base_url="https://api.fireworks.ai/inference/v1",
        )

    @classmethod
    def lite(cls, **kwargs: Any) -> Fireworks:
        """MiniMax M2P7 — cheapest."""
        return cls(model="accounts/fireworks/models/minimax-m2p7", **kwargs)

    @classmethod
    def standard(cls, **kwargs: Any) -> Fireworks:
        """DeepSeek V4 Pro — balanced."""
        return cls(model="accounts/fireworks/models/deepseek-v4-pro", **kwargs)

    @classmethod
    def pro(cls, **kwargs: Any) -> Fireworks:
        """Kimi K2P6 — most capable."""
        return cls(model="accounts/fireworks/models/kimi-k2p6", **kwargs)
