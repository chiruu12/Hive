"""Ollama provider — local models."""

from __future__ import annotations

from typing import Any

from hive.models.openai import OpenAI


class Ollama(OpenAI):
    """Ollama provider for local models. No API key needed."""

    def __init__(self, model: str = "llama3.2", host: str = "http://localhost:11434/v1"):
        super().__init__(model=model, api_key="ollama", base_url=host)

    @classmethod
    def lite(cls, **kwargs: Any) -> Ollama:
        """Small local model."""
        return cls(model="llama3.2", **kwargs)

    @classmethod
    def standard(cls, **kwargs: Any) -> Ollama:
        """Larger local model."""
        return cls(model="llama3.1", **kwargs)
