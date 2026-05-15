"""Model router — smart provider selection from models.yaml registry."""

import logging
from dataclasses import dataclass

from hive.models.registry import get_model_registry
from hive.runtime.providers import RuntimeProvider, create_runtime_provider

logger = logging.getLogger(__name__)


@dataclass
class ModelInfo:
    name: str
    provider: str
    available: bool


def create_provider(model_name: str) -> RuntimeProvider:
    """Route a model name to the correct RuntimeProvider."""
    return create_runtime_provider(model_name)


def get_routine_provider() -> RuntimeProvider:
    """Cheapest available model for existence loops and simple decisions."""
    reg = get_model_registry()
    model = reg.routing.routine
    p = create_runtime_provider(model)
    if p.available:
        return p

    for _prov, entry in reg.all_models():
        if entry.tier == "routine":
            p = create_runtime_provider(entry.id)
            if p.available:
                return p

    return create_runtime_provider(model)


def get_planning_provider() -> RuntimeProvider:
    """Best available model for plan generation and complex reasoning."""
    reg = get_model_registry()
    model = reg.routing.planning
    p = create_runtime_provider(model)
    if p.available:
        return p
    return get_routine_provider()


def get_events_provider() -> RuntimeProvider:
    """Model for life event choices."""
    reg = get_model_registry()
    model = reg.routing.events
    p = create_runtime_provider(model)
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

    has_groq = bool(get_env("GROQ_API_KEY"))
    if reg.groq:
        providers["Groq"] = [ModelInfo(m.id, "groq", has_groq) for m in reg.groq]

    has_openai = bool(get_env("OPENAI_API_KEY"))
    if reg.openai:
        providers["OpenAI"] = [ModelInfo(m.id, "openai", has_openai) for m in reg.openai]

    if reg.local:
        local_models = []
        for m in reg.local:
            p = create_runtime_provider(m.id)
            local_models.append(ModelInfo(m.id, m.provider or "local", p.available))
        providers["Local"] = local_models

    return providers
