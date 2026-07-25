"""Subprocess cleanup shared by toolkits that shell out."""

from __future__ import annotations

import asyncio
import contextlib


async def kill_and_reap(proc: asyncio.subprocess.Process | None) -> None:
    """Best-effort kill + reap so a failed/timed-out subprocess is never leaked.

    Without this, a process abandoned after ``asyncio.wait_for`` times out
    keeps running and its transport is garbage-collected after the event loop
    closes (ResourceWarning), or lingers as a zombie.
    """
    if proc is None or proc.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        proc.kill()
    with contextlib.suppress(Exception):
        await proc.wait()
