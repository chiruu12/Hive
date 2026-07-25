"""Event-driven wakeup sources for the daemon heartbeat.

Instead of sleeping a fixed heartbeat interval, the daemon can race
multiple :class:`WakeSource` instances and wake as soon as any fires.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class WakeSource(Protocol):
    """Protocol for a source that can wake the daemon mid-heartbeat."""

    async def wait(self) -> str:
        """Block until an event occurs.  Returns a short event-type label."""
        ...


class A2AWakeSource:
    """Wakes when any agent's A2A inbox changes.

    ``A2AStore`` appends messages to ``<hive>/a2a/<agent_id>/inbox.jsonl``, so a
    plain directory-entry count never changes on a new message. Instead we track
    the newest mtime across the whole ``a2a`` tree (files and dirs) and wake when
    it advances. Lightweight polling, no ``watchfiles`` dependency.
    """

    def __init__(self, a2a_dir: Path, poll_interval: float = 1.0) -> None:
        self._a2a_dir = a2a_dir
        self._poll = poll_interval
        self._last_mtime: float = -1.0

    def _max_mtime(self) -> float:
        newest = 0.0
        try:
            for path in self._a2a_dir.rglob("*"):
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                if mtime > newest:
                    newest = mtime
        except OSError:
            pass
        return newest

    async def wait(self) -> str:
        while True:
            newest = self._max_mtime()
            if self._last_mtime >= 0 and newest > self._last_mtime:
                self._last_mtime = newest
                return "a2a_message"
            self._last_mtime = newest
            await asyncio.sleep(self._poll)


class NudgeWakeSource:
    """Wakes when a new nudge file appears in the nudge queue.

    The nudge queue lives in ``<hive_dir>/nudges/`` as JSON files created
    by ``hive nudge``.  We poll the directory count.
    """

    def __init__(self, nudge_dir: Path, poll_interval: float = 1.0) -> None:
        self._dir = nudge_dir
        self._poll = poll_interval
        self._last_count: int = -1

    async def wait(self) -> str:
        while True:
            try:
                if self._dir.exists():
                    count = sum(1 for _ in self._dir.iterdir())
                    if self._last_count >= 0 and count > self._last_count:
                        self._last_count = count
                        return "nudge"
                    self._last_count = count
            except OSError:
                pass
            await asyncio.sleep(self._poll)


class FileWakeSource:
    """Wakes when a watched file's mtime changes."""

    def __init__(self, path: Path, poll_interval: float = 1.0) -> None:
        self._path = path
        self._poll = poll_interval
        self._last_mtime: float = 0.0

    async def wait(self) -> str:
        while True:
            try:
                if self._path.exists():
                    mtime = self._path.stat().st_mtime
                    if self._last_mtime > 0 and mtime != self._last_mtime:
                        self._last_mtime = mtime
                        return "file_change"
                    self._last_mtime = mtime
            except OSError:
                pass
            await asyncio.sleep(self._poll)


def touch_nudge_wake_file(hive_dir: Path, nudge_id: str) -> Path:
    """Create a marker file under ``<hive>/nudges/`` for :class:`NudgeWakeSource`.

    ``hive nudge`` persists the message in SQLite; this touch file lets the
    daemon wake before the next heartbeat without polling the database.
    """
    nudge_dir = hive_dir / "nudges"
    nudge_dir.mkdir(parents=True, exist_ok=True)
    path = nudge_dir / f"{nudge_id}.json"
    path.write_text("{}")
    return path


class CompositeWakeSource:
    """Races multiple wake sources and returns when the first fires.

    If no source fires within ``timeout`` seconds, returns ``"timeout"``.
    """

    def __init__(self, sources: list[WakeSource], timeout: float) -> None:
        self._sources = sources
        self._timeout = timeout

    async def wait(self) -> str:
        if not self._sources:
            await asyncio.sleep(self._timeout)
            return "timeout"

        tasks = [asyncio.create_task(src.wait()) for src in self._sources]
        try:
            done, _pending = await asyncio.wait(
                tasks, timeout=self._timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if done:
                return done.pop().result()
            return "timeout"
        finally:
            # Always cancel and reap every inner task -- including when this
            # coroutine is itself cancelled (e.g. the heartbeat timer fires
            # first). A bare ``except Exception`` misses CancelledError and
            # would leak the per-source polling tasks on every heartbeat.
            for t in tasks:
                if not t.done():
                    t.cancel()
            for t in tasks:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
