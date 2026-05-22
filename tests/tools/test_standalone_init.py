"""Tests for standalone toolkit initialization (db_path mode)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hive.tools.alarms.toolkit import AlarmToolkit
from hive.tools.knowledge.toolkit import KnowledgeToolkit
from hive.tools.tasks.toolkit import TaskToolkit


class TestTaskToolkitStandalone:
    @pytest.fixture
    def toolkit(self, tmp_path: Path) -> TaskToolkit:
        tk = TaskToolkit(db_path=tmp_path / "tasks.db")
        tk.bind("standalone-agent")
        return tk

    @pytest.mark.asyncio
    async def test_create_and_list(self, toolkit):
        await toolkit.create_task("Standalone task", priority="high")
        result = await toolkit.list_tasks()
        assert "Standalone task" in result
        assert "[high]" in result

    @pytest.mark.asyncio
    async def test_complete(self, toolkit):
        result = await toolkit.create_task("Do something")
        task_id = result.split()[2].rstrip(":")
        await toolkit.complete_task(task_id)
        done = await toolkit.list_tasks(status="done")
        assert "Do something" in done

    def test_raises_without_args(self):
        with pytest.raises(ValueError, match="requires either"):
            TaskToolkit()


class TestAlarmToolkitStandalone:
    @pytest.fixture
    def toolkit(self, tmp_path: Path) -> AlarmToolkit:
        tk = AlarmToolkit(db_path=tmp_path / "alarms.db")
        tk.bind("standalone-agent")
        return tk

    @pytest.mark.asyncio
    async def test_set_and_list(self, toolkit):
        await toolkit.set_alarm("Test alarm", minutes=5)
        result = await toolkit.list_alarms()
        assert "Test alarm" in result

    @pytest.mark.asyncio
    async def test_cancel(self, toolkit):
        result = await toolkit.set_alarm("Cancel me", seconds=60)
        alarm_id = result.split()[1]
        await toolkit.cancel_alarm(alarm_id)
        listing = await toolkit.list_alarms()
        assert "No pending" in listing

    def test_raises_without_args(self):
        with pytest.raises(ValueError, match="requires either"):
            AlarmToolkit()


class TestKnowledgeToolkitStandalone:
    @pytest.fixture
    def toolkit(self, tmp_path: Path) -> KnowledgeToolkit:
        tk = KnowledgeToolkit(memory_dir=tmp_path)
        tk.bind("standalone-agent")
        return tk

    @pytest.mark.asyncio
    async def test_save_and_search(self, toolkit):
        await toolkit.save_note("Python is great", tags="python")
        result = await toolkit.search_notes("Python")
        assert "Python" in result

    @pytest.mark.asyncio
    async def test_list_recent(self, toolkit):
        await toolkit.save_note("First note")
        await toolkit.save_note("Second note")
        result = await toolkit.list_recent_notes()
        assert "First note" in result
        assert "Second note" in result

    def test_raises_without_args(self):
        with pytest.raises(ValueError, match="requires either"):
            KnowledgeToolkit()
