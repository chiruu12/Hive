"""Integration tests for Mutter-ported toolkits.

Tests the full lifecycle of tasks, knowledge, and alarms together,
including cross-toolkit interactions and the daemon alarm check loop.

Run: uv run pytest tests/integration/test_mutter_toolkits.py -v
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from hive.memory.semantic import SemanticMemory
from hive.memory.store import HiveStore
from hive.tools.alarms.toolkit import AlarmToolkit, fire_notification
from hive.tools.knowledge.toolkit import KnowledgeToolkit
from hive.tools.tasks.toolkit import TaskToolkit


@pytest.fixture
async def store(tmp_path: Path) -> HiveStore:
    s = HiveStore(tmp_path / "hive.db")
    await s.initialize()
    return s


@pytest.fixture
def memory(tmp_path: Path) -> SemanticMemory:
    return SemanticMemory(tmp_path, "agent-1")


@pytest.fixture
def all_toolkits(store, memory):
    task_tk = TaskToolkit(store)
    knowledge_tk = KnowledgeToolkit(memory)
    alarm_tk = AlarmToolkit(store)
    for tk in (task_tk, knowledge_tk, alarm_tk):
        tk.bind("agent-1")
    return task_tk, knowledge_tk, alarm_tk


class TestFullLifecycle:
    @pytest.mark.asyncio
    async def test_task_lifecycle(self, all_toolkits):
        task_tk, _, _ = all_toolkits

        r1 = await task_tk.create_task("Design API schema", priority="high", due="Monday")
        assert "task-" in r1
        await task_tk.create_task("Write tests", priority="medium")
        r3 = await task_tk.create_task("Update README", priority="low")

        listing = await task_tk.list_tasks()
        assert "Design API" in listing
        assert "Write tests" in listing
        assert "Update README" in listing
        assert "[high]" in listing

        task_id = r1.split()[2].rstrip(":")
        await task_tk.complete_task(task_id)

        pending = await task_tk.list_tasks()
        assert "Design API" not in pending
        assert "Write tests" in pending

        done = await task_tk.list_tasks(status="done")
        assert "Design API" in done

        task_id3 = r3.split()[2].rstrip(":")
        await task_tk.delete_task(task_id3)
        pending2 = await task_tk.list_tasks()
        assert "Update README" not in pending2

    @pytest.mark.asyncio
    async def test_knowledge_lifecycle(self, all_toolkits):
        _, knowledge_tk, _ = all_toolkits

        await knowledge_tk.save_note("FastAPI uses Pydantic for validation", tags="python,api")
        await knowledge_tk.save_note("Express.js is a Node.js web framework", tags="js,web")
        await knowledge_tk.save_note("FastAPI supports async request handlers", tags="python,api")
        await knowledge_tk.save_note("SQLAlchemy is a Python ORM", tags="python,database")

        results = await knowledge_tk.search_notes("FastAPI Python")
        assert "FastAPI" in results
        assert "python" in results

        recent = await knowledge_tk.list_recent_notes(limit=2)
        lines = recent.strip().split("\n")
        assert len(lines) == 2

    @pytest.mark.asyncio
    async def test_alarm_lifecycle(self, all_toolkits):
        _, _, alarm_tk = all_toolkits

        await alarm_tk.set_alarm("Standup meeting", hours=1)
        r2 = await alarm_tk.set_alarm("Take a break", minutes=30)

        listing = await alarm_tk.list_alarms()
        assert "Standup meeting" in listing
        assert "Take a break" in listing

        alarm_id = r2.split()[1]
        await alarm_tk.cancel_alarm(alarm_id)

        listing2 = await alarm_tk.list_alarms()
        assert "Take a break" not in listing2
        assert "Standup meeting" in listing2

    @pytest.mark.asyncio
    async def test_cross_toolkit_workflow(self, all_toolkits):
        """Simulate an agent using all three toolkits together."""
        task_tk, knowledge_tk, alarm_tk = all_toolkits

        await task_tk.create_task("Research caching strategies", priority="high")
        await knowledge_tk.save_note(
            "Redis supports pub/sub, caching, and sorted sets", tags="database,caching"
        )
        await knowledge_tk.save_note(
            "Memcached is simpler but only supports key-value caching", tags="database,caching"
        )
        await alarm_tk.set_alarm("Review caching research", minutes=45)

        search = await knowledge_tk.search_notes("caching")
        assert "Redis" in search or "caching" in search

        tasks = await task_tk.list_tasks()
        assert "caching" in tasks

        alarms = await alarm_tk.list_alarms()
        assert "caching research" in alarms


class TestDaemonAlarmLoop:
    @pytest.mark.asyncio
    async def test_due_alarms_fire_and_clear(self, store):
        await store.save_alarm("a1", "agent-1", "Past alarm 1", "2020-01-01T00:00:00+00:00")
        await store.save_alarm("a2", "agent-1", "Past alarm 2", "2020-06-01T00:00:00+00:00")
        await store.save_alarm("a3", "agent-1", "Future alarm", "2099-01-01T00:00:00+00:00")

        due = await store.get_due_alarms()
        assert len(due) == 2

        for alarm in due:
            await store.mark_alarm_fired(alarm["alarm_id"])

        due_after = await store.get_due_alarms()
        assert len(due_after) == 0

        pending = await store.list_pending_alarms("agent-1")
        assert len(pending) == 1
        assert pending[0]["alarm_id"] == "a3"

    @pytest.mark.asyncio
    @patch("hive.tools.alarms.toolkit.platform.system", return_value="Darwin")
    @patch("hive.tools.alarms.toolkit.asyncio.create_subprocess_exec")
    async def test_notification_escaping(self, mock_exec, mock_system):
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.returncode = 0
        mock_exec.return_value = proc

        await fire_notification('He said "hello" and left')
        call_args = mock_exec.call_args
        script = call_args[0][2]
        assert '\\"hello\\"' in script


class TestMultiAgentIsolation:
    @pytest.mark.asyncio
    async def test_tasks_isolated_per_agent(self, store):
        tk1 = TaskToolkit(store)
        tk1.bind("agent-1")
        tk2 = TaskToolkit(store)
        tk2.bind("agent-2")

        await tk1.create_task("Agent 1 task")
        await tk2.create_task("Agent 2 task")

        list1 = await tk1.list_tasks()
        list2 = await tk2.list_tasks()

        assert "Agent 1 task" in list1
        assert "Agent 2 task" not in list1
        assert "Agent 2 task" in list2
        assert "Agent 1 task" not in list2

    @pytest.mark.asyncio
    async def test_alarms_isolated_per_agent(self, store):
        tk1 = AlarmToolkit(store)
        tk1.bind("agent-1")
        tk2 = AlarmToolkit(store)
        tk2.bind("agent-2")

        await tk1.set_alarm("Agent 1 alarm", minutes=10)
        await tk2.set_alarm("Agent 2 alarm", minutes=20)

        list1 = await tk1.list_alarms()
        list2 = await tk2.list_alarms()

        assert "Agent 1 alarm" in list1
        assert "Agent 2 alarm" not in list1
        assert "Agent 2 alarm" in list2
        assert "Agent 1 alarm" not in list2

    @pytest.mark.asyncio
    async def test_knowledge_isolated_per_agent(self, tmp_path):
        mem1 = SemanticMemory(tmp_path, "agent-1")
        mem2 = SemanticMemory(tmp_path, "agent-2")
        tk1 = KnowledgeToolkit(mem1)
        tk1.bind("agent-1")
        tk2 = KnowledgeToolkit(mem2)
        tk2.bind("agent-2")

        await tk1.save_note("Agent 1 secret knowledge")
        await tk2.save_note("Agent 2 secret knowledge")

        search1 = await tk1.search_notes("secret")
        search2 = await tk2.search_notes("secret")

        assert "Agent 1" in search1
        assert "Agent 2" not in search1
        assert "Agent 2" in search2
        assert "Agent 1" not in search2
