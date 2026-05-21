"""Factory function for creating providers by model name."""

from __future__ import annotations

from hive.models.base import BaseProvider


def create_runtime_provider(model_name: str) -> BaseProvider:
    """Create a provider from a model name string.

    Routing:
        claude-*          → Anthropic
        gpt-*             → OpenAI
        openrouter:*      → OpenRouter
        fireworks:*       → Fireworks
        groq:*            → Groq
        lmstudio:*        → LMStudio
        ollama:* / other  → Ollama
    """
    from hive.models.anthropic import Anthropic
    from hive.models.fireworks import Fireworks
    from hive.models.groq import Groq
    from hive.models.lmstudio import LMStudio
    from hive.models.ollama import Ollama
    from hive.models.openai import OpenAI
    from hive.models.openrouter import OpenRouter

    if "claude" in model_name or model_name.startswith("claude-"):
        return Anthropic(model=model_name)

    if model_name.startswith("gpt-"):
        return OpenAI(model=model_name)

    if model_name.startswith("openrouter:"):
        clean = model_name.removeprefix("openrouter:")
        return OpenRouter(model=clean)

    if model_name.startswith(("fireworks:", "accounts/fireworks")):
        clean = model_name.removeprefix("fireworks:")
        return Fireworks(model=clean)

    if model_name.startswith("groq:"):
        clean = model_name.removeprefix("groq:")
        return Groq(model=clean)

    if model_name.startswith("lmstudio:"):
        clean = model_name.removeprefix("lmstudio:")
        return LMStudio(model=clean)

    clean = model_name.removeprefix("ollama:")
    return Ollama(model=clean)
