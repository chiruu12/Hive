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
    async def test_uncomplete_task(self, toolkit):
        result = await toolkit.create_task("Reopen me")
        task_id = result.split()[2].rstrip(":")
        await toolkit.complete_task(task_id)
        reopen = await toolkit.uncomplete_task(task_id)
        assert "reopened" in reopen

        pending = await toolkit.list_tasks()
        assert "Reopen me" in pending

    @pytest.mark.asyncio
    async def test_uncomplete_already_pending(self, toolkit):
        result = await toolkit.create_task("Still pending")
        task_id = result.split()[2].rstrip(":")
        reopen = await toolkit.uncomplete_task(task_id)
        assert "not found or not completed" in reopen

    @pytest.mark.asyncio
    async def test_uncomplete_nonexistent(self, toolkit):
        result = await toolkit.uncomplete_task("task-nonexistent")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_update_task_description(self, toolkit):
        result = await toolkit.create_task("Old description")
        task_id = result.split()[2].rstrip(":")
        update = await toolkit.update_task(task_id, description="New description")
        assert "updated" in update

        listing = await toolkit.list_tasks()
        assert "New description" in listing

    @pytest.mark.asyncio
    async def test_update_task_priority(self, toolkit):
        result = await toolkit.create_task("Bump priority", priority="low")
        task_id = result.split()[2].rstrip(":")
        await toolkit.update_task(task_id, priority="high")

        listing = await toolkit.list_tasks()
        assert "high" in listing

    @pytest.mark.asyncio
    async def test_update_task_combined(self, toolkit):
        result = await toolkit.create_task("Original", priority="low")
        task_id = result.split()[2].rstrip(":")
        update = await toolkit.update_task(
            task_id, description="Updated", priority="high", due="Monday"
        )
        assert "updated" in update

        listing = await toolkit.list_tasks()
        assert "Updated" in listing
        assert "high" in listing
        assert "Monday" in listing

    @pytest.mark.asyncio
    async def test_update_task_nonexistent(self, toolkit):
        result = await toolkit.update_task("task-nonexistent", description="nope")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_update_task_invalid_priority(self, toolkit):
        result = await toolkit.create_task("Test")
        task_id = result.split()[2].rstrip(":")
        update = await toolkit.update_task(task_id, priority="urgent")
        assert "must be" in update

    @pytest.mark.asyncio
    async def test_list_tasks_filter_by_priority(self, toolkit):
        await toolkit.create_task("High one", priority="high")
        await toolkit.create_task("Low one", priority="low")
        result = await toolkit.list_tasks(priority="high")
        assert "High one" in result
        assert "Low one" not in result

    @pytest.mark.asyncio
    async def test_list_tasks_filter_no_match(self, toolkit):
        await toolkit.create_task("Low one", priority="low")
        result = await toolkit.list_tasks(priority="high")
        assert "No high pending tasks" in result

    @pytest.mark.asyncio
    async def test_update_task_nothing_to_update(self, toolkit):
        result = await toolkit.create_task("Stable")
        task_id = result.split()[2].rstrip(":")
        update = await toolkit.update_task(task_id)
        assert "Nothing to update" in update

    @pytest.mark.asyncio
    async def test_complete_task_twice(self, toolkit):
        result = await toolkit.create_task("Once only")
        task_id = result.split()[2].rstrip(":")
        await toolkit.complete_task(task_id)
        second = await toolkit.complete_task(task_id)
        assert "not found or already done" in second

    @pytest.mark.asyncio
    async def test_delete_then_complete(self, toolkit):
        result = await toolkit.create_task("Ghost task")
        task_id = result.split()[2].rstrip(":")
        await toolkit.delete_task(task_id)
        complete = await toolkit.complete_task(task_id)
        assert "not found" in complete

    @pytest.mark.asyncio
    async def test_tool_discovery(self, toolkit):
        tools = toolkit.get_tools()
        names = {t.name for t in tools}
        assert names == {
            "create_task",
            "list_tasks",
            "complete_task",
            "uncomplete_task",
            "delete_task",
            "update_task",
        }
