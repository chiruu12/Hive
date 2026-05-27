"""Memory backend protocol — pluggable storage for semantic memory."""

from __future__ import annotations

from typing import Any, Protocol

from hive.memory.semantic import MemoryRecord


class MemoryBackend(Protocol):
    """Protocol for memory storage backends.

    Implementations: TFIDFBackend (default), ChromaBackend (optional).
    """

    async def store(self, text: str, metadata: dict[str, Any] | None = None) -> str:
        """Store a memory. Returns memory_id."""
        ...

    async def search(self, query: str, top_k: int = 5) -> list[MemoryRecord]:
        """Search memories by similarity."""
        ...

    async def recent(self, limit: int = 5) -> list[MemoryRecord]:
        """Return most recent memories."""
        ...

    async def delete(self, memory_id: str) -> None:
        """Delete a memory by ID."""
        ...

    def count(self) -> int:
        """Return total number of stored memories."""
        ...

    # Optional methods (checked via hasattr at runtime):
    # async def recall(memory_id: str) -> MemoryRecord | None
    # async def consolidate(max_age_days: int, min_access: int) -> int
    # async def update(memory_id: str, text: str | None, metadata: dict | None) -> bool
    # def recent_sync(limit: int) -> list[MemoryRecord]
