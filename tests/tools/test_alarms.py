"""Tests for AlarmToolkit."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from hive.memory.store import HiveStore
from hive.tools.alarms.toolkit import AlarmToolkit, fire_notification


@pytest.fixture
async def store(tmp_path: Path) -> HiveStore:
    s = HiveStore(tmp_path / "hive.db")
    await s.initialize()
    return s


@pytest.fixture
def toolkit(store: HiveStore) -> AlarmToolkit:
    tk = AlarmToolkit(store)
    tk.bind("test-agent")
    return tk


class TestAlarmToolkit:
    @pytest.mark.asyncio
    async def test_set_alarm(self, toolkit):
        result = await toolkit.set_alarm("Stand up", minutes=30)
        assert "alarm-" in result
        assert "30m" in result
        assert "Stand up" in result

    @pytest.mark.asyncio
    async def test_set_alarm_zero_duration(self, toolkit):
        result = await toolkit.set_alarm("Bad alarm")
        assert "at least 1 second" in result

    @pytest.mark.asyncio
    async def test_list_alarms_empty(self, toolkit):
        result = await toolkit.list_alarms()
        assert "No pending" in result

    @pytest.mark.asyncio
    async def test_set_and_list(self, toolkit):
        await toolkit.set_alarm("Meeting", hours=1)
        await toolkit.set_alarm("Break", minutes=15)
        result = await toolkit.list_alarms()
        assert "Meeting" in result
        assert "Break" in result

    @pytest.mark.asyncio
    async def test_cancel_alarm(self, toolkit):
        result = await toolkit.set_alarm("Cancel me", seconds=60)
        alarm_id = result.split()[1]
        cancel_result = await toolkit.cancel_alarm(alarm_id)
        assert "cancelled" in cancel_result

        listing = await toolkit.list_alarms()
        assert "No pending" in listing

    @pytest.mark.asyncio
    async def test_cancel_nonexistent(self, toolkit):
        result = await toolkit.cancel_alarm("alarm-nonexistent")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_due_alarms(self, store):
        await store.save_alarm(
            "alarm-past",
            "test-agent",
            "Overdue",
            "2020-01-01T00:00:00+00:00",
        )
        due = await store.get_due_alarms()
        assert len(due) == 1
        assert due[0]["alarm_id"] == "alarm-past"

    @pytest.mark.asyncio
    async def test_mark_fired(self, store):
        await store.save_alarm(
            "alarm-fire",
            "test-agent",
            "Fire me",
            "2020-01-01T00:00:00+00:00",
        )
        await store.mark_alarm_fired("alarm-fire")
        due = await store.get_due_alarms()
        assert len(due) == 0

    @pytest.mark.asyncio
    async def test_set_alarm_at_future(self, toolkit):
        from datetime import UTC, datetime, timedelta

        future = (datetime.now(UTC) + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
        result = await toolkit.set_alarm_at("Future alarm", time=future)
        assert "alarm-" in result
        assert "Future alarm" in result

    @pytest.mark.asyncio
    async def test_set_alarm_at_unparseable(self, toolkit):
        result = await toolkit.set_alarm_at("Bad alarm", time="not-a-time-xyz")
        assert "Could not parse" in result

    @pytest.mark.asyncio
    async def test_set_alarm_at_past(self, toolkit):
        result = await toolkit.set_alarm_at("Past alarm", time="2020-01-01 10:00")
        assert "past" in result.lower()

    @pytest.mark.asyncio
    async def test_tool_discovery(self, toolkit):
        tools = toolkit.get_tools()
        names = {t.name for t in tools}
        assert names == {"set_alarm", "set_alarm_at", "list_alarms", "cancel_alarm"}


class TestFireNotification:
    @pytest.mark.asyncio
    @patch("hive.tools.alarms.toolkit.platform.system", return_value="Linux")
    async def test_non_macos_noop(self, mock_system):
        result = await fire_notification("test")
        assert result is True

    @pytest.mark.asyncio
    @patch("hive.tools.alarms.toolkit.platform.system", return_value="Darwin")
    @patch("hive.tools.alarms.toolkit.asyncio.create_subprocess_exec")
    async def test_macos_notification(self, mock_exec, mock_system):
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.returncode = 0
        mock_exec.return_value = proc

        result = await fire_notification("Time to stretch")
        assert result is True
        mock_exec.assert_called_once()
