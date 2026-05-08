"""Model router — smart provider selection from models.yaml registry."""

import logging
from dataclasses import dataclass

from hive.models.registry import get_model_registry

logger = logging.getLogger(__name__)


@dataclass
class ModelInfo:
    name: str
    provider: str
    available: bool


def create_provider(model_name: str):  # noqa: ANN201
    """Route a model name to the correct provider instance."""
    reg = get_model_registry()
    result = reg.find(model_name)
    provider_name = result[0] if result else _guess_provider(model_name)

    if provider_name == "anthropic" or model_name.startswith("claude-"):
        from hive.models.anthropic import AnthropicProvider

        return AnthropicProvider(model=model_name)

    if provider_name == "openai" or model_name.startswith("gpt-"):
        from hive.models.openai import OpenAIProvider

        return OpenAIProvider(model=model_name)

    if provider_name == "fireworks" or model_name.startswith(("fireworks:", "accounts/fireworks")):
        from hive.models.fireworks import FireworksProvider

        clean = model_name.removeprefix("fireworks:")
        return FireworksProvider(model=clean)

    if model_name.startswith("lmstudio:") or provider_name == "lmstudio":
        from hive.models.lmstudio import LMStudioProvider

        return LMStudioProvider(model=model_name.removeprefix("lmstudio:"))

    from hive.models.ollama import OllamaProvider

    return OllamaProvider(model=model_name.removeprefix("ollama:"))


def get_routine_provider():  # noqa: ANN201
    """Cheapest available model for existence loops and simple decisions."""
    reg = get_model_registry()
    model = reg.routing.routine
    p = create_provider(model)
    if p.available:
        return p

    for _prov, entry in reg.all_models():
        if entry.tier == "routine":
            p = create_provider(entry.id)
            if p.available:
                return p

    return create_provider(model)


def get_planning_provider():  # noqa: ANN201
    """Best available model for plan generation and complex reasoning."""
    reg = get_model_registry()
    model = reg.routing.planning
    p = create_provider(model)
    if p.available:
        return p
    return get_routine_provider()


def get_events_provider():  # noqa: ANN201
    """Model for life event choices."""
    reg = get_model_registry()
    model = reg.routing.events
    p = create_provider(model)
    if p.available:
        return p
    return get_routine_provider()


def detect_models() -> dict[str, list[ModelInfo]]:
    """Scan all providers for available models from registry."""
    from hive.config import get_env

    reg = get_model_registry()
    providers: dict[str, list[ModelInfo]] = {}

    has_anthropic = bool(get_env("ANTHROPIC_API_KEY"))
    if reg.anthropic:
        providers["Anthropic"] = [
            ModelInfo(m.id, "anthropic", has_anthropic) for m in reg.anthropic
        ]

    has_fireworks = bool(get_env("FIREWORKS_API_KEY"))
    if reg.fireworks:
        providers["Fireworks"] = [
            ModelInfo(m.id, "fireworks", has_fireworks) for m in reg.fireworks
        ]

    has_openai = bool(get_env("OPENAI_API_KEY"))
    if reg.openai:
        providers["OpenAI"] = [ModelInfo(m.id, "openai", has_openai) for m in reg.openai]

    if reg.local:
        local_models = []
        for m in reg.local:
            p = create_provider(m.id)
            local_models.append(ModelInfo(m.id, m.provider or "local", p.available))
        providers["Local"] = local_models

    return providers


def _guess_provider(model_name: str) -> str:
    if "claude" in model_name:
        return "anthropic"
    if "gpt" in model_name:
        return "openai"
    if "fireworks" in model_name:
        return "fireworks"
    if "lmstudio" in model_name:
        return "lmstudio"
    return "ollama"
