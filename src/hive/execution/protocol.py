"""Tool execution protocol - interface for tool implementations."""

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


class ToolResult(BaseModel):
    """Result from executing a tool."""

    success: bool
    output: str
    error: str | None = None
    artifacts: list[str] = []  # file paths or references created


class ToolDefinition(BaseModel):
    """Metadata for a registered tool."""

    name: str
    description: str
    tool_type: str = "built-in"  # built-in, synthesized, mcp
    parameters: dict[str, str] = {}  # param_name: description


@runtime_checkable
class ToolExecutor(Protocol):
    """Interface for tool implementations."""

    @property
    def definition(self) -> ToolDefinition: ...

    async def execute(self, agent_id: str, **params: Any) -> ToolResult: ...


# Decorator for simple function-based tools
def tool(name: str, description: str, **param_descriptions: str) -> Callable:
    """Decorator to register a function as a Hive tool."""

    def decorator(func: Callable) -> Callable:
        func._tool_name = name  # type: ignore[attr-defined]
        func._tool_description = description  # type: ignore[attr-defined]
        func._tool_params = param_descriptions  # type: ignore[attr-defined]
        return func

    return decorator
