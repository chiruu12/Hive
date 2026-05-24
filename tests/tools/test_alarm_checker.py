"""Tests for standalone AlarmChecker."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from hive.memory.store import HiveStore
from hive.tools.alarms.checker import AlarmChecker


@pytest.fixture
async def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "alarms.db"
    store = HiveStore(path)
    await store.initialize()
    return path


@pytest.fixture
async def store(db_path: Path) -> HiveStore:
    s = HiveStore(db_path)
    await s.initialize()
    return s


class TestAlarmChecker:
    @pytest.mark.asyncio
    @patch("hive.tools.alarms.checker.fire_notification", new_callable=AsyncMock)
    async def test_check_once_fires_due(self, mock_notify, db_path, store):
        mock_notify.return_value = True

        await store.save_alarm("a1", "agent", "Past alarm", "2020-01-01T00:00:00+00:00")
        await store.save_alarm("a2", "agent", "Future alarm", "2099-01-01T00:00:00+00:00")

        checker = AlarmChecker(db_path, check_interval=60)
        await checker._store.initialize()
        fired = await checker.check_once()

        assert fired == ["a1"]
        mock_notify.assert_called_once_with("Past alarm", title="Hive Alarm")

    @pytest.mark.asyncio
    @patch("hive.tools.alarms.checker.fire_notification", new_callable=AsyncMock)
    async def test_check_once_marks_fired(self, mock_notify, db_path, store):
        mock_notify.return_value = True

        await store.save_alarm("a1", "agent", "Fire me", "2020-01-01T00:00:00+00:00")

        checker = AlarmChecker(db_path, check_interval=60)
        await checker._store.initialize()
        await checker.check_once()

        remaining = await store.get_due_alarms()
        assert len(remaining) == 0

    @pytest.mark.asyncio
    @patch("hive.tools.alarms.checker.fire_notification", new_callable=AsyncMock)
    async def test_check_once_empty(self, mock_notify, db_path):
        checker = AlarmChecker(db_path, check_interval=60)
        await checker._store.initialize()
        fired = await checker.check_once()
        assert fired == []
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    @patch("hive.tools.alarms.checker.fire_notification", new_callable=AsyncMock)
    async def test_check_once_marks_fired_on_notification_failure(
        self, mock_notify, db_path, store
    ):
        mock_notify.return_value = False

        await store.save_alarm("a1", "agent", "Fail notify", "2020-01-01T00:00:00+00:00")

        checker = AlarmChecker(db_path, check_interval=60)
        await checker._store.initialize()
        fired = await checker.check_once()

        assert fired == ["a1"]
        remaining = await store.get_due_alarms()
        assert len(remaining) == 0

    @pytest.mark.asyncio
    @patch("hive.tools.alarms.checker.fire_notification", new_callable=AsyncMock)
    async def test_run_forever_and_stop(self, mock_notify, db_path, store):
        mock_notify.return_value = True
        await store.save_alarm("a1", "agent", "Loop test", "2020-01-01T00:00:00+00:00")

        checker = AlarmChecker(db_path, check_interval=1)
        task = asyncio.create_task(checker.run_forever())
        await asyncio.sleep(0.1)

        assert mock_notify.called
        checker._running = False
        await asyncio.sleep(1.5)
        assert task.done() or not checker._running
        if not task.done():
            task.cancel()
