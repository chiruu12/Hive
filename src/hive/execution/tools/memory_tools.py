"""Memory tools — persistent key-value store per agent."""

import json
from pathlib import Path

from hive.execution.protocol import ToolResult, tool

_MEMORY_DIR: Path | None = None


def set_memory_dir(hive_dir: Path) -> None:
    global _MEMORY_DIR
    _MEMORY_DIR = hive_dir / "agent_memory"
    _MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def _agent_memory_path(agent_id: str) -> Path:
    if _MEMORY_DIR is None:
        raise RuntimeError("Memory dir not initialized")
    path = _MEMORY_DIR / f"{agent_id}.json"
    if not path.exists():
        path.write_text("{}")
    return path


@tool("memory_set", description="Store a value in agent memory", key="key", value="value")
async def memory_set(agent_id: str, key: str = "", value: str = "") -> ToolResult:
    """Persist a key-value pair in agent-scoped memory."""
    if not key:
        return ToolResult(success=False, output="No key specified", error="missing_key")
    path = _agent_memory_path(agent_id)
    data = json.loads(path.read_text())
    data[key] = value
    path.write_text(json.dumps(data, indent=2))
    return ToolResult(success=True, output=f"Stored: {key}")


@tool("memory_get", description="Retrieve a value from agent memory", key="key to retrieve")
async def memory_get(agent_id: str, key: str = "") -> ToolResult:
    """Retrieve a value from agent-scoped memory."""
    if not key:
        return ToolResult(success=False, output="No key specified", error="missing_key")
    path = _agent_memory_path(agent_id)
    data = json.loads(path.read_text())
    value = data.get(key)
    if value is None:
        return ToolResult(success=False, output=f"Key not found: {key}", error="not_found")
    return ToolResult(success=True, output=str(value))
