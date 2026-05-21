"""Tests for TaskToolkit."""

from __future__ import annotations

from pathlib import Path

import pytest

from hive.memory.store import HiveStore
from hive.tools.tasks.toolkit import TaskToolkit


@pytest.fixture
async def store(tmp_path: Path) -> HiveStore:
    s = HiveStore(tmp_path / "hive.db")
    await s.initialize()
    return s


@pytest.fixture
def toolkit(store: HiveStore) -> TaskToolkit:
    tk = TaskToolkit(store)
    tk.bind("test-agent")
    return tk


class TestTaskToolkit:
    @pytest.mark.asyncio
    async def test_create_task(self, toolkit):
        result = await toolkit.create_task("Build API", priority="high")
        assert "Created task" in result
        assert "Build API" in result
        assert "high" in result

    @pytest.mark.asyncio
    async def test_create_task_invalid_priority(self, toolkit):
        result = await toolkit.create_task("Test", priority="urgent")
        assert "must be" in result

    @pytest.mark.asyncio
    async def test_list_tasks_empty(self, toolkit):
        result = await toolkit.list_tasks()
        assert "No pending tasks" in result

    @pytest.mark.asyncio
    async def test_create_and_list(self, toolkit):
        await toolkit.create_task("Task A", priority="high")
        await toolkit.create_task("Task B", priority="low", due="Friday")
        result = await toolkit.list_tasks()
        assert "Task A" in result
        assert "Task B" in result
        assert "high" in result
        assert "Friday" in result

    @pytest.mark.asyncio
    async def test_complete_task(self, toolkit, store):
        result = await toolkit.create_task("Finish tests")
        task_id = result.split()[2].rstrip(":")
        complete_result = await toolkit.complete_task(task_id)
        assert "completed" in complete_result

        pending = await toolkit.list_tasks()
        assert "No pending tasks" in pending

        done = await toolkit.list_tasks(status="done")
        assert "Finish tests" in done

    @pytest.mark.asyncio
    async def test_complete_nonexistent(self, toolkit):
        result = await toolkit.complete_task("task-nonexistent")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_delete_task(self, toolkit):
        result = await toolkit.create_task("Temporary task")
        task_id = result.split()[2].rstrip(":")
        delete_result = await toolkit.delete_task(task_id)
        assert "deleted" in delete_result

        pending = await toolkit.list_tasks()
        assert "No pending tasks" in pending

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, toolkit):
        result = await toolkit.delete_task("task-nonexistent")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_tool_discovery(self, toolkit):
        tools = toolkit.get_tools()
        names = {t.name for t in tools}
        assert names == {"create_task", "list_tasks", "complete_task", "delete_task"}
