"""Knowledge toolkit — save, search, and browse notes via semantic memory."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hive.tools.base import Toolkit, tool

if TYPE_CHECKING:
    from hive.memory.semantic import SemanticMemory


class KnowledgeToolkit(Toolkit):
    """Tools for storing and searching knowledge notes.

    Usage:
        # Daemon mode (shared memory):
        tk = KnowledgeToolkit(memory=semantic_memory)

        # Standalone mode (creates own memory):
        tk = KnowledgeToolkit(memory_dir="/path/to/data")
    """

    def __init__(
        self,
        memory: SemanticMemory | None = None,
        memory_dir: str | Path | None = None,
    ):
        self._memory: SemanticMemory | None = None
        self._memory_dir: Path | None = None
        if memory is not None:
            self._memory = memory
        elif memory_dir is not None:
            self._memory_dir = Path(memory_dir)
        else:
            raise ValueError("KnowledgeToolkit requires either memory or memory_dir")

    def bind(self, agent_id: str) -> None:
        super().bind(agent_id)
        if self._memory_dir is not None:
            from hive.memory.semantic import SemanticMemory

            self._memory = SemanticMemory(self._memory_dir, agent_id)

    def rebind(self, agent_id: str) -> None:
        super().rebind(agent_id)
        if self._memory_dir is not None:
            from hive.memory.semantic import SemanticMemory

            self._memory = SemanticMemory(self._memory_dir, agent_id)

    def query_recent(self, limit: int = 20) -> list[dict[str, object]]:
        """Query recent notes as dicts. For host application use, not an agent tool."""
        if self._memory is None:
            raise RuntimeError("KnowledgeToolkit is not bound to an agent yet.")
        records = self._memory.recent(limit)
        return [
            {
                "id": r.memory_id,
                "content": r.thought,
                "created_at": r.ts.isoformat(),
                "tags": r.metadata.get("tags", ""),
            }
            for r in records
        ]

    @property
    def instructions(self) -> str:
        return (
            "You can save notes to a knowledge base, search them by topic, "
            "browse recent entries, delete notes, and update existing notes."
        )

    @tool()
    async def save_note(self, content: str, tags: str = "") -> str:
        """Save a note to the knowledge base.

        Args:
            content: The note content to save.
            tags: Optional comma-separated tags for categorization.
        """
        if self._memory is None:
            raise RuntimeError("KnowledgeToolkit is not bound to an agent yet.")
        metadata = {"tags": tags} if tags else {}
        mid = await self._memory.store(content, metadata)
        return f"Saved note {mid}: {content[:80]}"

    @tool()
    async def search_notes(self, query: str, limit: str = "5") -> str:
        """Search the knowledge base by topic or keywords.

        Args:
            query: What to search for.
            limit: Maximum number of results.
        """
        assert self._memory is not None
        results = await self._memory.search(query, top_k=int(float(limit)))
        if not results:
            return "No matching notes found."
        lines = []
        for r in results:
            tags = r.metadata.get("tags", "")
            tag_str = f" [{tags}]" if tags else ""
            lines.append(f"- {r.memory_id}: {r.thought[:100]}{tag_str}")
        return "\n".join(lines)

    @tool()
    async def list_recent_notes(self, limit: str = "10") -> str:
        """List the most recent notes.

        Args:
            limit: How many notes to show.
        """
        assert self._memory is not None
        notes = self._memory.recent(int(float(limit)))
        if not notes:
            return "No notes yet."
        lines = []
        for n in notes:
            ts = n.ts.strftime("%Y-%m-%d %H:%M")
            tags = n.metadata.get("tags", "")
            tag_str = f" [{tags}]" if tags else ""
            lines.append(f"- {n.memory_id} ({ts}): {n.thought[:80]}{tag_str}")
        return "\n".join(lines)

    @tool()
    async def delete_note(self, note_id: str) -> str:
        """Delete a note from the knowledge base.

        Args:
            note_id: The note ID to delete.
        """
        assert self._memory is not None
        count_before = self._memory.count()
        await self._memory.forget(note_id)
        if self._memory.count() < count_before:
            return f"Note {note_id} deleted."
        return f"Note {note_id} not found."

    @tool()
    async def update_note(self, note_id: str, content: str = "", tags: str = "") -> str:
        """Update an existing note's content or tags.

        Args:
            note_id: The note ID to update.
            content: New content (leave empty to keep current).
            tags: New comma-separated tags (leave empty to keep current).
        """
        assert self._memory is not None
        text = content or None
        meta = {"tags": tags} if tags else None
        if text is None and meta is None:
            return "Nothing to update — provide content or tags."
        existing = await self._memory.recall(note_id)
        if existing is None:
            return f"Note {note_id} not found."
        ok = await self._memory.update(note_id, text, meta)
        if not ok:
            return f"Note {note_id} could not be updated (backend may not support updates)."
        return f"Note {note_id} updated."
