"""Memory tools — persistent key-value store per agent via context."""

import json

from hive.execution.context import ExecutionContext
from hive.execution.protocol import ToolResult, tool


@tool("memory_set", description="Store a value in agent memory", key="key", value="value")
async def memory_set(
    agent_id: str, context: ExecutionContext | None = None, key: str = "", value: str = ""
) -> ToolResult:
    """Persist a key-value pair in agent-scoped memory."""
    if not context:
        return ToolResult(success=False, output="No context", error="no_context")
    if not key:
        return ToolResult(success=False, output="No key specified", error="missing_key")
    path = context.memory_dir / f"{agent_id}.json"
    if not path.exists():
        path.write_text("{}")
    data = json.loads(path.read_text())
    data[key] = value
    path.write_text(json.dumps(data, indent=2))
    return ToolResult(success=True, output=f"Stored: {key}")


@tool("memory_get", description="Retrieve a value from agent memory", key="key to retrieve")
async def memory_get(
    agent_id: str, context: ExecutionContext | None = None, key: str = ""
) -> ToolResult:
    """Retrieve a value from agent-scoped memory."""
    if not context:
        return ToolResult(success=False, output="No context", error="no_context")
    if not key:
        return ToolResult(success=False, output="No key specified", error="missing_key")
    path = context.memory_dir / f"{agent_id}.json"
    if not path.exists():
        return ToolResult(success=False, output=f"Key not found: {key}", error="not_found")
    data = json.loads(path.read_text())
    value = data.get(key)
    if value is None:
        return ToolResult(success=False, output=f"Key not found: {key}", error="not_found")
    return ToolResult(success=True, output=str(value))
