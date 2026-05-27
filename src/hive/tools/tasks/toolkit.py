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
            "tasks, mark tasks as done, reopen completed tasks, update task "
            "details, or delete them."
        )

    async def query_tasks(
        self, status: str = "pending", priority: str | None = None
    ) -> list[dict[str, Any]]:
        """Query tasks for the bound agent. For host application use, not an agent tool."""
        if not self._agent_id:
            raise RuntimeError("TaskToolkit is not bound to an agent yet.")
        await self._ensure_init()
        return await self._store.list_tasks(self._agent_id, status, priority)

    async def query_all_tasks(
        self, status: str = "pending", priority: str | None = None
    ) -> list[dict[str, Any]]:
        """Query tasks across all agents. For host application use, not an agent tool."""
        await self._ensure_init()
        return await self._store.list_all_tasks(status, priority)

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
    async def list_tasks(self, status: str = "pending", priority: str = "") -> str:
        """List tasks filtered by status and optionally by priority.

        Args:
            status: Filter by status — pending or done.
            priority: Optional priority filter — high, medium, or low.
        """
        await self._ensure_init()
        prio = priority or None
        if prio and prio not in ("high", "medium", "low"):
            return "Priority must be high, medium, or low."
        tasks = await self._store.list_tasks(self._agent_id, status, prio)
        if not tasks:
            filt = f" {priority}" if priority else ""
            return f"No{filt} {status} tasks."
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
    async def uncomplete_task(self, task_id: str) -> str:
        """Reopen a completed task, setting it back to pending.

        Args:
            task_id: The task ID to uncomplete.
        """
        await self._ensure_init()
        ok = await self._store.uncomplete_task(task_id)
        return f"Task {task_id} reopened." if ok else f"Task {task_id} not found or not completed."

    @tool()
    async def delete_task(self, task_id: str) -> str:
        """Delete a task.

        Args:
            task_id: The task ID to delete.
        """
        await self._ensure_init()
        ok = await self._store.delete_task(task_id)
        return f"Task {task_id} deleted." if ok else f"Task {task_id} not found."

    @tool()
    async def update_task(
        self, task_id: str, description: str = "", priority: str = "", due: str = ""
    ) -> str:
        """Update a task's description, priority, or due date.

        Args:
            task_id: The task ID to update.
            description: New description (leave empty to keep current).
            priority: New priority — high, medium, or low (leave empty to keep current).
            due: New due date (leave empty to keep current).
        """
        await self._ensure_init()
        desc = description or None
        prio = priority or None
        due_date = due or None
        if prio and prio not in ("high", "medium", "low"):
            return "Priority must be high, medium, or low."
        if not any([desc, prio, due_date]):
            return "Nothing to update — provide at least one field."
        ok = await self._store.update_task(task_id, desc, prio, due_date)
        return f"Task {task_id} updated." if ok else f"Task {task_id} not found."
