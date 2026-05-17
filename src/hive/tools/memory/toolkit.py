"""Memory toolkit — agent-scoped key-value memory stored as JSON files."""

import json
from pathlib import Path
from uuid import uuid4

from hive.tools.base import Toolkit, tool


class MemoryToolkit(Toolkit):
    """Agent-scoped key-value memory stored as JSON files.

    Usage:
        tk = MemoryToolkit()                           # defaults to .hive/memory/
        tk = MemoryToolkit(path="/my/memory/dir")       # explicit path
    """

    def __init__(self, path: str | Path | None = None, agent_id: str = ""):
        self._dir = Path(path) if path else Path.cwd() / ".hive" / "agent_memory"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._agent_id = agent_id

    def _ensure_id(self) -> str:
        if not self._agent_id:
            self._agent_id = f"agent-{uuid4().hex[:8]}"
        return self._agent_id

    @property
    def _path(self) -> Path:
        return self._dir / f"{self._ensure_id()}.json"

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        data: dict[str, str] = json.loads(self._path.read_text())
        return data

    def _save(self, data: dict[str, str]) -> None:
        self._path.write_text(json.dumps(data, indent=2))

    @tool()
    def memory_get(self, key: str) -> str:
        """Retrieve a previously stored value from your memory.

        Args:
            key: The key to look up.
        """
        data = self._load()
        value = data.get(key)
        if value is None:
            return f"Key not found: {key}. Available keys: {', '.join(data.keys()) or 'none'}"
        return str(value)

    @tool()
    def memory_set(self, key: str, value: str) -> str:
        """Store a value in your persistent memory for later retrieval.

        Args:
            key: The key to store under.
            value: The value to store.
        """
        data = self._load()
        data[key] = value
        self._save(data)
        return f"Stored: {key}"
