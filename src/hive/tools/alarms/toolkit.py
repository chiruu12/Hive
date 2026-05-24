"""Alarm toolkit — set, list, and cancel timed reminders."""

from __future__ import annotations

import asyncio
import logging
import platform
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from hive.tools.base import Toolkit, tool

if TYPE_CHECKING:
    from hive.memory.store import HiveStore

logger = logging.getLogger(__name__)


async def fire_notification(description: str, title: str = "Hive Alarm") -> bool:
    """Fire a macOS notification. No-op on other platforms."""
    if platform.system() != "Darwin":
        logger.info("Alarm (non-macOS): %s", description)
        return True

    escaped = (
        description.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")
    )
    escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')
    script = f'display notification "{escaped}" with title "{escaped_title}" sound name "Glass"'
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript",
            "-e",
            script,
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
        # Daemon mode (shared store):
        tk = AlarmToolkit(store=hive_store)

        # Standalone mode (own DB connection):
        tk = AlarmToolkit(db_path="/path/to/app.db")
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
            raise ValueError("AlarmToolkit requires either store or db_path")

    async def _ensure_init(self) -> None:
        if not self._initialized:
            await self._store.initialize()
            self._initialized = True

    @property
    def instructions(self) -> str:
        return (
            "You can set timed alarms that fire macOS notifications. "
            "Specify hours, minutes, and/or seconds from now."
        )

    async def query_pending_alarms(self) -> list[dict[str, Any]]:
        """Query pending alarms for the bound agent. For host application use."""
        if not self._agent_id:
            raise RuntimeError("AlarmToolkit is not bound to an agent yet.")
        await self._ensure_init()
        return await self._store.list_pending_alarms(self._agent_id)

    async def query_all_pending_alarms(self) -> list[dict[str, Any]]:
        """Query pending alarms across all agents. For host application use."""
        await self._ensure_init()
        return await self._store.list_all_pending_alarms()

    @tool()
    async def set_alarm(
        self,
        description: str,
        hours: str = "0",
        minutes: str = "0",
        seconds: str = "0",
    ) -> str:
        """Set an alarm that fires after a delay.

        Args:
            description: What this alarm is for.
            hours: Hours from now.
            minutes: Minutes from now.
            seconds: Seconds from now.
        """
        await self._ensure_init()
        h = int(float(hours))
        m = int(float(minutes))
        s = int(float(seconds))
        total = timedelta(hours=h, minutes=m, seconds=s)
        if total.total_seconds() <= 0:
            return "Alarm must be at least 1 second in the future."

        fire_at = datetime.now(UTC) + total
        alarm_id = f"alarm-{uuid4().hex[:8]}"
        await self._store.save_alarm(alarm_id, self._agent_id, description, fire_at.isoformat())

        parts = []
        if h:
            parts.append(f"{h}h")
        if m:
            parts.append(f"{m}m")
        if s:
            parts.append(f"{s}s")
        label = " ".join(parts) or "now"

        return f"Alarm {alarm_id} set for {label} from now: {description}"

    @tool()
    async def list_alarms(self) -> str:
        """List all pending alarms."""
        await self._ensure_init()
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
        await self._ensure_init()
        ok = await self._store.cancel_alarm(alarm_id)
        if ok:
            return f"Alarm {alarm_id} cancelled."
        return f"Alarm {alarm_id} not found or already fired."
