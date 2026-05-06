"""Tool registry — auto-discover and dispatch tool calls with context injection."""

import importlib
import inspect
import logging
import pkgutil
from collections.abc import Callable
from typing import Any

from hive.execution.context import ExecutionContext
from hive.execution.protocol import ToolDefinition, ToolResult

logger = logging.getLogger(__name__)

_instance: "ToolRegistry | None" = None


def get_registry() -> "ToolRegistry":
    if _instance is None:
        raise RuntimeError("ToolRegistry not initialized")
    return _instance


class ToolRegistry:
    """Registry that discovers and dispatches tool calls, injecting ExecutionContext."""

    def __init__(self, ctx: ExecutionContext) -> None:
        global _instance
        self._ctx = ctx
        self._tools: dict[str, Callable] = {}
        self._definitions: dict[str, ToolDefinition] = {}
        _instance = self

    def discover(self) -> None:
        import hive.execution.tools as tools_pkg

        for _importer, modname, _ispkg in pkgutil.iter_modules(tools_pkg.__path__):
            module = importlib.import_module(f"hive.execution.tools.{modname}")
            for _name, obj in inspect.getmembers(module):
                if callable(obj) and hasattr(obj, "_tool_name"):
                    self.register(obj)

    def register(self, func: Callable) -> None:
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
        func = self._tools.get(tool_name)
        if not func:
            return ToolResult(
                success=False,
                output=f"Unknown tool: {tool_name}",
                error="tool_not_found",
            )
        try:
            sig = inspect.signature(func)
            valid_params: dict[str, Any] = {}
            for k, v in params.items():
                if k in sig.parameters and k not in ("agent_id", "context"):
                    valid_params[k] = v
            if "context" in sig.parameters:
                valid_params["context"] = self._ctx
            return await func(agent_id=agent_id, **valid_params)
        except Exception as e:
            logger.error("Tool %s failed: %s", tool_name, e)
            return ToolResult(success=False, output=str(e), error="execution_error")

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._definitions.values())

    def get_tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def get_tool_schemas(self) -> str:
        lines = []
        for defn in self._definitions.values():
            params_str = ", ".join(f"{k}: {v}" for k, v in defn.parameters.items())
            lines.append(f"- {defn.name}({params_str}): {defn.description}")
        return "\n".join(lines)
