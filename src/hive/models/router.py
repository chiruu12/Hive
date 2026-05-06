"""Model router - provider factory and detection."""

import shutil
from dataclasses import dataclass

from hive.models.claude import ClaudeCLIProvider


@dataclass
class ModelInfo:
    name: str
    provider: str
    available: bool


def create_provider(model_name: str, **kwargs: object) -> ClaudeCLIProvider:
    """Create the appropriate provider for a model string."""
    if shutil.which("claude"):
        return ClaudeCLIProvider(model=model_name)
    raise RuntimeError("No model provider available. Install Claude Code CLI to use Hive.")


def detect_models() -> dict[str, list[ModelInfo]]:
    """Detect available models and providers. Used by `hive models` command."""
    providers: dict[str, list[ModelInfo]] = {}

    claude_available = shutil.which("claude") is not None
    providers["Claude CLI"] = [
        ModelInfo("claude-opus-4-6", "claude-cli", claude_available),
        ModelInfo("claude-sonnet-4-6", "claude-cli", claude_available),
        ModelInfo("claude-haiku-4-5", "claude-cli", claude_available),
    ]

    return providers
