"""Standalone alarm checker — polls for due alarms independently of the daemon."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from hive.memory.store import HiveStore
from hive.tools.alarms.toolkit import fire_notification

logger = logging.getLogger(__name__)


class AlarmChecker:
    """Polls the alarms table and fires notifications for due alarms.

    Works independently of the HiveDaemon — suitable for FastAPI servers
    or any long-running process that needs alarm functionality.

    Usage::

        checker = AlarmChecker(db_path="app.db", check_interval=15)

        # In FastAPI lifespan:
        async def lifespan(app):
            task = asyncio.create_task(checker.run_forever())
            yield
            await checker.stop()
    """

    def __init__(self, db_path: str | Path, check_interval: int = 15):
        self._store = HiveStore(Path(db_path))
        self._interval = check_interval
        self._running = False
        self._initialized = False
        self._task: asyncio.Task[None] | None = None

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self._store.initialize()
            self._initialized = True

    async def run_forever(self) -> None:
        """Poll for due alarms continuously until stopped."""
        await self._ensure_initialized()
        self._running = True
        while self._running:
            try:
                await self.check_once()
            except Exception as e:
                logger.warning("Alarm check failed: %s", e)
            await asyncio.sleep(self._interval)

    async def check_once(self) -> list[str]:
        """Check for due alarms, fire notifications, return fired IDs."""
        await self._ensure_initialized()
        due = await self._store.get_due_alarms()
        fired_ids = []
        for alarm in due:
            ok = await fire_notification(alarm["description"])
            if not ok:
                logger.warning(
                    "Alarm %s notification failed, marking fired anyway",
                    alarm["alarm_id"],
                )
            await self._store.mark_alarm_fired(alarm["alarm_id"])
            fired_ids.append(alarm["alarm_id"])
        return fired_ids

    async def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
