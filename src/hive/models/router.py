"""Model router — smart provider selection by model name and task complexity."""

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ANTHROPIC_MODELS = {"claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-6"}
OPENAI_MODELS = {"gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"}
ROUTINE_PREFERENCE = ["claude-haiku-4-5", "gpt-4o-mini"]
PLANNING_PREFERENCE = ["claude-sonnet-4-6", "gpt-4o"]


@dataclass
class ModelInfo:
    name: str
    provider: str
    available: bool


def create_provider(model_name: str):  # noqa: ANN201
    """Route a model name to the correct provider instance."""
    if model_name in ANTHROPIC_MODELS or model_name.startswith("claude-"):
        from hive.models.anthropic import AnthropicProvider

        return AnthropicProvider(model=model_name)

    if model_name in OPENAI_MODELS or model_name.startswith("gpt-"):
        from hive.models.openai import OpenAIProvider

        return OpenAIProvider(model=model_name)

    from hive.models.ollama import OllamaProvider

    return OllamaProvider(model=model_name)


def get_routine_provider():  # noqa: ANN201
    """Cheapest available model for existence loops and simple decisions."""
    for model in ROUTINE_PREFERENCE:
        p = create_provider(model)
        if p.available:
            return p

    from hive.models.ollama import OllamaProvider

    fallback = OllamaProvider()
    if fallback.available:
        return fallback

    return create_provider(ROUTINE_PREFERENCE[0])


def get_planning_provider():  # noqa: ANN201
    """Best available model for plan generation and complex reasoning."""
    for model in PLANNING_PREFERENCE:
        p = create_provider(model)
        if p.available:
            return p
    return get_routine_provider()


def detect_models() -> dict[str, list[ModelInfo]]:
    """Scan all providers for available models."""
    providers: dict[str, list[ModelInfo]] = {}

    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    providers["Anthropic"] = [
        ModelInfo(m, "anthropic", has_anthropic) for m in sorted(ANTHROPIC_MODELS)
    ]

    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    providers["OpenAI"] = [ModelInfo(m, "openai", has_openai) for m in sorted(OPENAI_MODELS)]

    from hive.models.ollama import OllamaProvider

    ollama = OllamaProvider()
    providers["Ollama (local)"] = [
        ModelInfo("llama3.2", "ollama", ollama.available),
        ModelInfo("mistral", "ollama", ollama.available),
        ModelInfo("qwen2.5", "ollama", ollama.available),
    ]

    return providers
