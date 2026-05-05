"""Tool registry — auto-discover and dispatch tool calls."""

import importlib
import inspect
import logging
import pkgutil
from collections.abc import Callable
from typing import Any

from hive.execution.protocol import ToolDefinition, ToolResult

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry that discovers and dispatches tool calls."""

    def __init__(self) -> None:
        self._tools: dict[str, Callable] = {}
        self._definitions: dict[str, ToolDefinition] = {}

    def discover(self) -> None:
        """Auto-discover tools from hive.execution.tools package."""
        import hive.execution.tools as tools_pkg

        for importer, modname, ispkg in pkgutil.iter_modules(tools_pkg.__path__):
            module = importlib.import_module(f"hive.execution.tools.{modname}")
            for name, obj in inspect.getmembers(module):
                if callable(obj) and hasattr(obj, "_tool_name"):
                    self.register(obj)

    def register(self, func: Callable) -> None:
        """Register a decorated tool function."""
        tool_name = getattr(func, "_tool_name", None)
        if not tool_name:
            return
        self._tools[tool_name] = func
        self._definitions[tool_name] = ToolDefinition(
            name=tool_name,
            description=getattr(func, "_tool_description", ""),
            parameters=getattr(func, "_tool_params", {}),
        )
        logger.debug("Registered tool: %s", tool_name)

    async def execute(self, tool_name: str, agent_id: str, **params: Any) -> ToolResult:
        """Execute a tool by name."""
        func = self._tools.get(tool_name)
        if not func:
            return ToolResult(
                success=False,
                output=f"Unknown tool: {tool_name}",
                error="tool_not_found",
            )
        try:
            return await func(agent_id=agent_id, **params)
        except Exception as e:
            logger.error("Tool %s failed: %s", tool_name, e)
            return ToolResult(success=False, output=str(e), error="execution_error")

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._definitions.values())

    def get_tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def get_tool_schemas(self) -> str:
        """Format tool list for LLM prompt injection."""
        lines = []
        for defn in self._definitions.values():
            params_str = ", ".join(f"{k}: {v}" for k, v in defn.parameters.items())
            lines.append(f"- {defn.name}({params_str}): {defn.description}")
        return "\n".join(lines)
