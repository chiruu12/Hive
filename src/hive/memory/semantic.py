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
            self._backend: Any = backend
        else:
            from hive.memory.tfidf_backend import TFIDFBackend

            self._backend = TFIDFBackend(hive_dir, agent_id)

    async def store(self, thought: str, metadata: dict[str, Any] | None = None) -> str:
        result: str = await self._backend.store(thought, metadata or {})
        return result

    async def search(self, query: str, top_k: int = 5) -> list[MemoryRecord]:
        result: list[MemoryRecord] = await self._backend.search(query, top_k)
        return result

    async def recall(self, memory_id: str) -> MemoryRecord | None:
        if hasattr(self._backend, "recall"):
            result: MemoryRecord | None = await self._backend.recall(memory_id)
            return result
        return None

    async def forget(self, memory_id: str) -> None:
        await self._backend.delete(memory_id)

    async def update(
        self,
        memory_id: str,
        thought: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        if hasattr(self._backend, "update"):
            result: bool = await self._backend.update(memory_id, thought, metadata)
            return result
        return False

    async def consolidate(self, max_age_days: int = 30, min_access: int = 2) -> int:
        if hasattr(self._backend, "consolidate"):
            result: int = await self._backend.consolidate(max_age_days, min_access)
            return result
        return 0

    def count(self) -> int:
        result: int = self._backend.count()
        return result

    def recent(self, limit: int = 5) -> list[MemoryRecord]:
        if hasattr(self._backend, "recent_sync"):
            result: list[MemoryRecord] = self._backend.recent_sync(limit)
            return result
        import asyncio

        try:
            asyncio.get_running_loop()
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                r: list[MemoryRecord] = pool.submit(
                    asyncio.run, self._backend.recent(limit)
                ).result()
                return r
        except RuntimeError:
            r2: list[MemoryRecord] = asyncio.run(self._backend.recent(limit))
            return r2
