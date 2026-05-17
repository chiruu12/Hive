"""Tests for scheduled goals — ScheduleToolkit and store methods."""

from pathlib import Path

import pytest

from hive.memory.store import HiveStore
from hive.tools.schedule import ScheduleToolkit


@pytest.fixture
async def store(tmp_path: Path) -> HiveStore:
    s = HiveStore(tmp_path / "hive.db")
    await s.initialize()
    return s


class TestScheduleStore:
    @pytest.mark.asyncio
    async def test_save_and_list_schedule(self, store: HiveStore):
        await store.save_schedule("s-1", "agent-a", "Check inbox", 5)
        schedules = await store.list_schedules("agent-a")
        assert len(schedules) == 1
        assert schedules[0]["objective"] == "Check inbox"
        assert schedules[0]["every_n_cycles"] == 5

    @pytest.mark.asyncio
    async def test_get_due_schedules(self, store: HiveStore):
        await store.save_schedule("s-1", "agent-a", "Daily check", 3)
        due = await store.get_due_schedules("agent-a", 3)
        assert len(due) == 1

        due_early = await store.get_due_schedules("agent-a", 2)
        assert len(due_early) == 0

    @pytest.mark.asyncio
    async def test_fire_schedule_updates_last_fired(self, store: HiveStore):
        await store.save_schedule("s-1", "agent-a", "Task", 5)
        await store.fire_schedule("s-1", 5)

        due_at_5 = await store.get_due_schedules("agent-a", 5)
        assert len(due_at_5) == 0

        due_at_10 = await store.get_due_schedules("agent-a", 10)
        assert len(due_at_10) == 1

    @pytest.mark.asyncio
    async def test_disable_schedule(self, store: HiveStore):
        await store.save_schedule("s-1", "agent-a", "Task", 5)
        await store.disable_schedule("s-1")

        schedules = await store.list_schedules("agent-a")
        assert len(schedules) == 0


class TestScheduleToolkit:
    @pytest.mark.asyncio
    async def test_tool_discovery(self, store: HiveStore):
        tk = ScheduleToolkit(store, "agent-a")
        tools = tk.get_tools()
        names = {t.name for t in tools}
        assert "schedule_goal" in names
        assert "list_schedules" in names
        assert "cancel_schedule" in names

    @pytest.mark.asyncio
    async def test_schedule_and_list(self, store: HiveStore):
        tk = ScheduleToolkit(store, "agent-a")
        result = await tk.schedule_goal("Check email", 10)
        assert "Scheduled" in result
        assert "every 10 cycles" in result

        listing = await tk.list_schedules()
        assert "Check email" in listing

    @pytest.mark.asyncio
    async def test_cancel_schedule(self, store: HiveStore):
        tk = ScheduleToolkit(store, "agent-a")
        await tk.schedule_goal("Temp task", 5)
        schedules = await store.list_schedules("agent-a")
        sid = schedules[0]["schedule_id"]

        result = await tk.cancel_schedule(sid)
        assert "cancelled" in result

        listing = await tk.list_schedules()
        assert "No scheduled goals" in listing

    @pytest.mark.asyncio
    async def test_reject_zero_interval(self, store: HiveStore):
        tk = ScheduleToolkit(store, "agent-a")
        result = await tk.schedule_goal("Bad", 0)
        assert "at least 1" in result
