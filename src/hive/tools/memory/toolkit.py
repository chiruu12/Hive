"""Memory toolkit — agent-scoped key-value memory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from hive.config import get_config
from hive.tools.base import Toolkit, tool

if TYPE_CHECKING:
    from hive.memory.semantic import SemanticMemory


class MemoryToolkit(Toolkit):
    """Agent-scoped key-value memory.

    When ``memory.unified`` is enabled (default), reads and writes delegate to the
    same :class:`~hive.memory.semantic.SemanticMemory` backend the daemon uses.
    Legacy JSON files under ``agent_memory/`` are imported once on first access.

    Usage:
        # Daemon mode (shared semantic backend):
        tk = MemoryToolkit(semantic=semantic_memory, hive_dir=hive_dir)

        # Legacy JSON-only mode (``memory.unified: false``):
        tk = MemoryToolkit(path="/my/memory/dir")
    """

    def __init__(
        self,
        path: str | Path | None = None,
        agent_id: str = "",
        *,
        semantic: SemanticMemory | None = None,
        hive_dir: Path | None = None,
        unified: bool | None = None,
    ):
        cfg = get_config()
        self._unified = cfg.memory.unified if unified is None else unified
        self._semantic = semantic
        self._hive_dir = hive_dir
        self._legacy_dir = Path(path) if path else Path.cwd() / ".hive" / "agent_memory"
        self._legacy_dir.mkdir(parents=True, exist_ok=True)
        self._agent_id = agent_id

    def _ensure_id(self) -> str:
        if not self._agent_id:
            self._agent_id = f"agent-{uuid4().hex[:8]}"
        return self._agent_id

    @property
    def _path(self) -> Path:
        return self._legacy_dir / f"{self._ensure_id()}.json"

    def bind(self, agent_id: str) -> None:
        super().bind(agent_id)
        if self._unified:
            self._ensure_semantic()

    def rebind(self, agent_id: str) -> None:
        super().rebind(agent_id)
        if self._unified:
            self._semantic = None
            self._ensure_semantic()

    def _ensure_semantic(self) -> SemanticMemory:
        if not self._unified:
            raise RuntimeError("Semantic memory is not enabled (memory.unified=false).")
        if self._semantic is not None:
            return self._semantic
        if self._hive_dir is None:
            raise RuntimeError("MemoryToolkit requires hive_dir when unified=true.")

        from hive.memory.migration import ensure_legacy_migrated
        from hive.memory.semantic import SemanticMemory

        agent_id = self._ensure_id()
        self._semantic = SemanticMemory(self._hive_dir, agent_id)
        ensure_legacy_migrated(self._semantic, self._hive_dir, agent_id, self._legacy_dir)
        return self._semantic

    def _load_legacy(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        data: dict[str, str] = json.loads(self._path.read_text())
        return data

    def _save_legacy(self, data: dict[str, str]) -> None:
        self._path.write_text(json.dumps(data, indent=2))

    def _list_kv_keys(self) -> list[str]:
        mem = self._ensure_semantic()
        keys: list[str] = []
        for rec in mem.recent(limit=200):
            if rec.metadata.get("type") == "kv":
                key = rec.metadata.get("key")
                if isinstance(key, str) and key not in keys:
                    keys.append(key)
        return keys

    def _find_kv_value(self, key: str) -> str | None:
        mem = self._ensure_semantic()
        for rec in mem.recent(limit=200):
            if rec.metadata.get("type") == "kv" and rec.metadata.get("key") == key:
                return rec.thought
        return None

    @tool()
    def memory_get(self, key: str) -> str:
        """Retrieve a previously stored value from your memory.

        Args:
            key: The key to look up.
        """
        if not self._unified:
            data = self._load_legacy()
            value = data.get(key)
            if value is None:
                return f"Key not found: {key}. Available keys: {', '.join(data.keys()) or 'none'}"
            return str(value)

        value = self._find_kv_value(key)
        if value is None:
            keys = self._list_kv_keys()
            return f"Key not found: {key}. Available keys: {', '.join(keys) or 'none'}"
        return str(value)

    @tool()
    def memory_set(self, key: str, value: str) -> str:
        """Store a value in your persistent memory for later retrieval.

        Args:
            key: The key to store under.
            value: The value to store.
        """
        if not self._unified:
            data = self._load_legacy()
            data[key] = value
            self._save_legacy(data)
            return f"Stored: {key}"

        from hive.memory._sync import run_async

        mem = self._ensure_semantic()
        run_async(mem.store(value, metadata={"type": "kv", "key": key, "source": "memory_toolkit"}))
        return f"Stored: {key}"
