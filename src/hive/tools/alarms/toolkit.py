"""Alarm toolkit — set, list, and cancel timed reminders."""

from __future__ import annotations

import asyncio
import logging
import platform
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from hive.tools.base import Toolkit, tool

if TYPE_CHECKING:
    from hive.memory.store import HiveStore

logger = logging.getLogger(__name__)


async def fire_notification(description: str) -> bool:
    """Fire a macOS notification. No-op on other platforms."""
    if platform.system() != "Darwin":
        logger.info("Alarm (non-macOS): %s", description)
        return True

    escaped = (
        description.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", " ")
        .replace("\r", " ")
    )
    script = (
        f'display notification "{escaped}" '
        f'with title "Hive Alarm" sound name "Glass"'
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=5)
        return proc.returncode == 0
    except Exception as e:
        logger.warning("Alarm notification failed: %s", e)
        return False


class AlarmToolkit(Toolkit):
    """Tools for setting and managing alarms.

    Usage:
        tk = AlarmToolkit(store=my_store)
    """

    def __init__(self, store: HiveStore):
        self._store = store

    @property
    def instructions(self) -> str:
        return (
            "You can set timed alarms that fire macOS notifications. "
            "Specify hours, minutes, and/or seconds from now."
        )

    @tool()
    async def set_alarm(
        self,
        description: str,
        hours: int = 0,
        minutes: int = 0,
        seconds: int = 0,
    ) -> str:
        """Set an alarm that fires after a delay.

        Args:
            description: What this alarm is for.
            hours: Hours from now.
            minutes: Minutes from now.
            seconds: Seconds from now.
        """
        total = timedelta(hours=hours, minutes=minutes, seconds=seconds)
        if total.total_seconds() <= 0:
            return "Alarm must be at least 1 second in the future."

        fire_at = datetime.now(UTC) + total
        alarm_id = f"alarm-{uuid4().hex[:8]}"
        await self._store.save_alarm(
            alarm_id, self._agent_id, description, fire_at.isoformat()
        )

        parts = []
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds:
            parts.append(f"{seconds}s")
        label = " ".join(parts) or "now"

        return f"Alarm {alarm_id} set for {label} from now: {description}"

    @tool()
    async def list_alarms(self) -> str:
        """List all pending alarms."""
        alarms = await self._store.list_pending_alarms(self._agent_id)
        if not alarms:
            return "No pending alarms."
        lines = []
        for a in alarms:
            lines.append(f"- {a['alarm_id']}: {a['description']} (fires at {a['fire_at']})")
        return "\n".join(lines)

    @tool()
    async def cancel_alarm(self, alarm_id: str) -> str:
        """Cancel a pending alarm.

        Args:
            alarm_id: The alarm ID to cancel.
        """
        ok = await self._store.cancel_alarm(alarm_id)
        if ok:
            return f"Alarm {alarm_id} cancelled."
        return f"Alarm {alarm_id} not found or already fired."
