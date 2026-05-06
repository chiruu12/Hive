"""Model provider protocol - the interface all LLM backends must implement."""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class ModelResponse(BaseModel):
    """Standard response from any model provider."""

    content: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None


class ToolCall(BaseModel):
    """A tool invocation requested by the model."""

    tool_name: str
    arguments: dict[str, object]


class PlanStep(BaseModel):
    """A single step in an agent's execution plan."""

    tool: str
    params: dict[str, object]
    rationale: str


@runtime_checkable
class ModelProvider(Protocol):
    """Interface for LLM providers. Implement this to add a new backend."""

    @property
    def name(self) -> str: ...

    @property
    def available(self) -> bool: ...

    async def complete(
        self,
        messages: list[dict[str, str]],
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> ModelResponse: ...

    async def plan(
        self,
        objective: str,
        available_tools: list[str],
        context: str | None = None,
    ) -> list[PlanStep]: ...
