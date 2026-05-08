"""Model registry — loads model config from models.yaml."""

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_DEFAULT_MODELS_PATHS = [
    Path.cwd() / "models.yaml",
    Path(__file__).resolve().parent.parent.parent.parent / "models.yaml",
]


class ModelEntry(BaseModel):
    id: str
    display: str = ""
    provider: str = ""
    cost_input_per_1k: float = 0.001
    cost_output_per_1k: float = 0.005
    max_tokens: int = 8192
    tier: str = "routine"


class RoutingConfig(BaseModel):
    routine: str = "claude-haiku-4-5"
    planning: str = "claude-sonnet-4-6"
    events: str = "claude-haiku-4-5"


class ModelRegistry(BaseModel):
    routing: RoutingConfig = RoutingConfig()
    anthropic: list[ModelEntry] = []
    fireworks: list[ModelEntry] = []
    openai: list[ModelEntry] = []
    local: list[ModelEntry] = []

    def all_models(self) -> list[tuple[str, ModelEntry]]:
        result = []
        for m in self.anthropic:
            result.append(("anthropic", m))
        for m in self.fireworks:
            result.append(("fireworks", m))
        for m in self.openai:
            result.append(("openai", m))
        for m in self.local:
            result.append((m.provider or "local", m))
        return result

    def find(self, model_id: str) -> tuple[str, ModelEntry] | None:
        for provider, entry in self.all_models():
            if entry.id == model_id:
                return (provider, entry)
        return None

    def cost_per_1k(self, model_id: str) -> dict[str, float]:
        result = self.find(model_id)
        if result:
            _, entry = result
            return {"input": entry.cost_input_per_1k, "output": entry.cost_output_per_1k}
        return {"input": 0.001, "output": 0.005}


_registry: ModelRegistry | None = None


def load_model_registry(path: Path | None = None) -> ModelRegistry:
    global _registry

    if path and path.exists():
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        _registry = ModelRegistry(**data)
        return _registry

    for p in _DEFAULT_MODELS_PATHS:
        if p.exists():
            with open(p) as f:
                data = yaml.safe_load(f) or {}
            _registry = ModelRegistry(**data)
            return _registry

    _registry = ModelRegistry()
    return _registry


def get_model_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        return load_model_registry()
    return _registry
