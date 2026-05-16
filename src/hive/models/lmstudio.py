"""LM Studio provider — local models."""

from __future__ import annotations

from typing import Any

from hive.models.openai import OpenAI


class LMStudio(OpenAI):
    """LM Studio provider for local models. No API key needed."""

    def __init__(
        self,
        model: str = "loaded-model",
        host: str = "http://localhost:1234/v1",
    ):
        super().__init__(model=model, api_key="lm-studio", base_url=host)

    @classmethod
    def lite(cls, **kwargs: Any) -> LMStudio:
        """Auto-detect loaded model."""
        return cls(model="loaded-model", **kwargs)

    @classmethod
    def standard(cls, **kwargs: Any) -> LMStudio:
        """Auto-detect loaded model."""
        return cls(model="loaded-model", **kwargs)
