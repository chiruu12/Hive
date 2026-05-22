"""Semantic memory — store and retrieve thoughts by similarity."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class MemoryRecord(BaseModel):
    memory_id: str
    agent_id: str
    thought: str
    metadata: dict[str, Any] = {}
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    access_count: int = 0
    last_accessed: datetime | None = None


class SemanticMemory:
    """Store thoughts and retrieve by keyword similarity.

    Accepts an optional backend for pluggable storage. Defaults to TFIDFBackend.
    """

    def __init__(
        self,
        hive_dir: Path,
        agent_id: str,
        backend: Any | None = None,
    ):
        self._agent_id = agent_id
        self._hive_dir = hive_dir

        if backend is not None:
            self._backend = backend
        else:
            from hive.memory.tfidf_backend import TFIDFBackend

            self._backend = TFIDFBackend(hive_dir, agent_id)

    async def store(self, thought: str, metadata: dict[str, Any] | None = None) -> str:
        return await self._backend.store(thought, metadata or {})

    async def search(self, query: str, top_k: int = 5) -> list[MemoryRecord]:
        return await self._backend.search(query, top_k)

    async def recall(self, memory_id: str) -> MemoryRecord | None:
        if hasattr(self._backend, "recall"):
            return await self._backend.recall(memory_id)
        return None

    async def forget(self, memory_id: str) -> None:
        await self._backend.delete(memory_id)

    async def consolidate(self, max_age_days: int = 30, min_access: int = 2) -> int:
        if hasattr(self._backend, "consolidate"):
            return await self._backend.consolidate(max_age_days, min_access)
        return 0

    def count(self) -> int:
        return self._backend.count()

    def recent(self, limit: int = 5) -> list[MemoryRecord]:
        if hasattr(self._backend, "recent_sync"):
            return self._backend.recent_sync(limit)
        import asyncio

        try:
            asyncio.get_running_loop()
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, self._backend.recent(limit)).result()
        except RuntimeError:
            return asyncio.run(self._backend.recent(limit))
