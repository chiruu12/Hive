"""Clipboard toolkit — copy text, notes, tasks, and links to the system clipboard."""

from __future__ import annotations

import asyncio
import logging
import platform
from pathlib import Path
from typing import TYPE_CHECKING

from hive.tools.base import Toolkit, tool

if TYPE_CHECKING:
    from hive.memory.semantic import SemanticMemory
    from hive.memory.store import HiveStore

logger = logging.getLogger(__name__)


async def _copy_to_system_clipboard(text: str) -> bool:
    """Copy text to system clipboard. Supports macOS and Linux."""
    system = platform.system()
    if system == "Darwin":
        cmd = ["pbcopy"]
    elif system == "Linux":
        cmd = ["xclip", "-selection", "clipboard"]
    else:
        logger.warning("Clipboard not supported on %s", system)
        return False

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(input=text.encode()), timeout=5)
        return proc.returncode == 0
    except Exception as e:
        logger.warning("Clipboard copy failed: %s", e)
        return False


async def _read_from_system_clipboard() -> str | None:
    """Read text from the system clipboard. Supports macOS and Linux.

    Returns the clipboard text, or None if reading is unsupported or failed.
    """
    system = platform.system()
    if system == "Darwin":
        cmd = ["pbpaste"]
    elif system == "Linux":
        cmd = ["xclip", "-selection", "clipboard", "-o"]
    else:
        logger.warning("Clipboard not supported on %s", system)
        return None

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode != 0:
            return None
        return stdout.decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("Clipboard read failed: %s", e)
        return None


class ClipboardToolkit(Toolkit):
    """Tools for copying content to the system clipboard.

    Usage:
        # With access to store + memory (can copy tasks, notes, links):
        tk = ClipboardToolkit(store=hive_store, memory=semantic_memory)

        # Standalone (copy text only):
        tk = ClipboardToolkit()
    """

    def __init__(
        self,
        store: HiveStore | None = None,
        memory: SemanticMemory | None = None,
        db_path: str | Path | None = None,
        memory_dir: str | Path | None = None,
    ) -> None:
        self._store: HiveStore | None = None
        self._memory: SemanticMemory | None = None
        self._memory_dir: Path | None = None
        self._initialized = False

        if store is not None:
            self._store = store
            self._initialized = True
        elif db_path is not None:
            from hive.memory.store import HiveStore as _Store

            self._store = _Store(Path(db_path))

        if memory is not None:
            self._memory = memory
        elif memory_dir is not None:
            self._memory_dir = Path(memory_dir)

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

    async def _ensure_init(self) -> None:
        if not self._initialized and self._store is not None:
            await self._store.initialize()
            self._initialized = True

    @property
    def instructions(self) -> str:
        return (
            "You can copy text, notes, tasks, or links to the user's clipboard, "
            "and read what's currently on the clipboard."
        )

    @tool()
    async def copy_to_clipboard(self, text: str) -> str:
        """Copy text to the system clipboard.

        Args:
            text: The text to copy.
        """
        ok = await _copy_to_system_clipboard(text)
        if ok:
            preview = text[:80] + ("..." if len(text) > 80 else "")
            return f"Copied to clipboard: {preview}"
        return "Failed to copy to clipboard."

    @tool()
    async def read_clipboard(self) -> str:
        """Read the current text contents of the system clipboard.

        Use this when the user refers to something they have already copied --
        for example "save the link I just copied" or "add this to my notes".
        """
        text = await _read_from_system_clipboard()
        if text is None:
            return "Couldn't read the clipboard on this system."
        text = text.strip()
        if not text:
            return "The clipboard is empty."
        return text

    @tool()
    async def copy_note(self, note_id: str) -> str:
        """Copy a note's content to the clipboard.

        Args:
            note_id: The note/memory ID to copy.
        """
        if self._memory is None:
            return "No knowledge base available."

        record = await self._memory.recall(note_id)
        if record is None:
            return f"Note {note_id} not found."

        ok = await _copy_to_system_clipboard(record.thought)
        if ok:
            preview = record.thought[:80] + ("..." if len(record.thought) > 80 else "")
            return f"Copied note to clipboard: {preview}"
        return "Failed to copy to clipboard."

    @tool()
    async def copy_task(self, task_id: str) -> str:
        """Copy a task's description to the clipboard.

        Args:
            task_id: The task ID to copy.
        """
        if self._store is None:
            return "No task store available."

        await self._ensure_init()
        tasks = await self._store.list_tasks(self._agent_id, "pending")
        tasks += await self._store.list_tasks(self._agent_id, "done")

        task = next((t for t in tasks if t["task_id"] == task_id), None)
        if task is None:
            return f"Task {task_id} not found."

        text = task["description"]
        if task.get("due_date"):
            text += f" (due: {task['due_date']})"

        ok = await _copy_to_system_clipboard(text)
        if ok:
            return f"Copied task to clipboard: {text[:80]}"
        return "Failed to copy to clipboard."

    @tool()
    async def copy_link(self, query: str) -> str:
        """Find a saved link by search and copy its URL to the clipboard.

        Args:
            query: Search query to find the link.
        """
        if self._memory is None:
            return "No knowledge base available."

        results = await self._memory.search(query, top_k=5)
        links = [r for r in results if r.metadata.get("type") == "link"]

        if not links:
            return f"No saved link matching '{query}'."

        link = links[0]
        url = link.metadata.get("url", "")
        if not url:
            return "Link found but has no URL."

        ok = await _copy_to_system_clipboard(url)
        if ok:
            title = link.metadata.get("title", url)
            return f"Copied URL to clipboard: {title} ({url})"
        return "Failed to copy to clipboard."
