"""Task management toolkit — create, list, complete, and delete tasks."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from hive.tools.base import Toolkit, tool

if TYPE_CHECKING:
    from hive.memory.store import HiveStore


class TaskToolkit(Toolkit):
    """Tools for managing tasks.

    Usage:
        # Daemon mode (shared store):
        tk = TaskToolkit(store=hive_store)

        # Standalone mode (own DB connection):
        tk = TaskToolkit(db_path="/path/to/app.db")
    """

    def __init__(
        self,
        store: HiveStore | None = None,
        db_path: str | Path | None = None,
    ):
        self._initialized = False
        if store is not None:
            self._store = store
            self._initialized = True
        elif db_path is not None:
            from hive.memory.store import HiveStore as _Store

            self._store = _Store(Path(db_path))
        else:
            raise ValueError("TaskToolkit requires either store or db_path")

    async def _ensure_init(self) -> None:
        if not self._initialized:
            await self._store.initialize()
            self._initialized = True

    @property
    def instructions(self) -> str:
        return (
            "You can manage tasks: create new tasks, list pending or completed "
            "tasks, mark tasks as done, or delete them."
        )

    async def query_tasks(self, status: str = "pending") -> list[dict[str, Any]]:
        """Query tasks for the bound agent. For host application use, not an agent tool."""
        if not self._agent_id:
            raise RuntimeError("TaskToolkit is not bound to an agent yet.")
        await self._ensure_init()
        return await self._store.list_tasks(self._agent_id, status)

    async def query_all_tasks(self, status: str = "pending") -> list[dict[str, Any]]:
        """Query tasks across all agents. For host application use, not an agent tool."""
        await self._ensure_init()
        import aiosqlite

        async with aiosqlite.connect(self._store._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    @tool()
    async def create_task(self, description: str, priority: str = "medium", due: str = "") -> str:
        """Create a new task.

        Args:
            description: What needs to be done.
            priority: Priority level — high, medium, or low.
            due: Optional due date or deadline description.
        """
        await self._ensure_init()
        if priority not in ("high", "medium", "low"):
            return "Priority must be high, medium, or low."
        task_id = f"task-{uuid4().hex[:8]}"
        await self._store.save_task(
            task_id,
            self._agent_id,
            description,
            priority,
            due or None,
        )
        return f"Created task {task_id}: {description} (priority={priority})"

    @tool()
    async def list_tasks(self, status: str = "pending") -> str:
        """List tasks filtered by status.

        Args:
            status: Filter by status — pending or done.
        """
        await self._ensure_init()
        tasks = await self._store.list_tasks(self._agent_id, status)
        if not tasks:
            return f"No {status} tasks."
        lines = []
        for t in tasks:
            due = f" due={t['due_date']}" if t["due_date"] else ""
            lines.append(f"- {t['task_id']}: {t['description']} [{t['priority']}]{due}")
        return "\n".join(lines)

    @tool()
    async def complete_task(self, task_id: str) -> str:
        """Mark a task as done.

        Args:
            task_id: The task ID to complete.
        """
        await self._ensure_init()
        ok = await self._store.complete_task(task_id)
        return f"Task {task_id} completed." if ok else f"Task {task_id} not found or already done."

    @tool()
    async def delete_task(self, task_id: str) -> str:
        """Delete a task.

        Args:
            task_id: The task ID to delete.
        """
        await self._ensure_init()
        ok = await self._store.delete_task(task_id)
        return f"Task {task_id} deleted." if ok else f"Task {task_id} not found."
