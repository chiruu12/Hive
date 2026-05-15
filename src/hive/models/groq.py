"""Groq provider — fast inference."""

from __future__ import annotations

from typing import Any

from hive.models.openai import OpenAI


class Groq(OpenAI):
    """Groq provider for fast inference on open models."""

    def __init__(self, model: str = "llama-3.3-70b-versatile", api_key: str | None = None):
        from hive.config import get_env

        key = api_key or get_env("GROQ_API_KEY") or None
        super().__init__(
            model=model,
            api_key=key,
            base_url="https://api.groq.com/openai/v1",
        )

    @classmethod
    def lite(cls, **kwargs: Any) -> Groq:
        """Llama 3.1 8B — fastest, cheapest."""
        return cls(model="llama-3.1-8b-instant", **kwargs)

    @classmethod
    def standard(cls, **kwargs: Any) -> Groq:
        """Llama 3.3 70B — balanced."""
        return cls(model="llama-3.3-70b-versatile", **kwargs)
