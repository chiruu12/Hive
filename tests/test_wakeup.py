"""Tests for WakeSource protocol and implementations."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from hive.daemon.wakeup import (
    A2AWakeSource,
    CompositeWakeSource,
    FileWakeSource,
    NudgeWakeSource,
    touch_nudge_wake_file,
)


class TestCompositeWakeSource:
    @pytest.mark.asyncio
    async def test_returns_timeout_when_no_sources(self):
        src = CompositeWakeSource([], timeout=0.1)
        result = await src.wait()
        assert result == "timeout"

    @pytest.mark.asyncio
    async def test_returns_first_source_result(self):
        class FastSource:
            async def wait(self) -> str:
                return "fast_event"

        src = CompositeWakeSource([FastSource()], timeout=5.0)
        result = await src.wait()
        assert result == "fast_event"

    @pytest.mark.asyncio
    async def test_timeout_when_sources_never_fire(self):
        class NeverSource:
            async def wait(self) -> str:
                await asyncio.sleep(999)
                return "never"

        src = CompositeWakeSource([NeverSource()], timeout=0.1)
        result = await src.wait()
        assert result == "timeout"


class TestFileWakeSource:
    @pytest.mark.asyncio
    async def test_detects_file_change(self, tmp_path: Path):
        watch_file = tmp_path / "test.txt"
        watch_file.write_text("initial")
        src = FileWakeSource(watch_file, poll_interval=0.05)
        # Prime the initial mtime
        await asyncio.sleep(0.1)
        src._last_mtime = watch_file.stat().st_mtime

        # Change the file in background
        async def change_file():
            await asyncio.sleep(0.1)
            watch_file.write_text("changed")

        change_task = asyncio.create_task(change_file())
        result = await asyncio.wait_for(src.wait(), timeout=2.0)
        await change_task
        assert result == "file_change"


class TestA2AWakeSource:
    @pytest.mark.asyncio
    async def test_detects_appended_message(self, tmp_path: Path):
        # A2AStore appends to <a2a>/<agent_id>/inbox.jsonl -- the source must
        # wake on an append, not just a new directory entry.
        a2a_dir = tmp_path / "a2a"
        agent_inbox = a2a_dir / "bob"
        agent_inbox.mkdir(parents=True)
        inbox_file = agent_inbox / "inbox.jsonl"
        inbox_file.write_text('{"msg": 1}\n')

        src = A2AWakeSource(a2a_dir, poll_interval=0.05)
        await asyncio.sleep(0.1)
        # Prime the baseline mtime.
        src._last_mtime = src._max_mtime()

        async def append_message():
            await asyncio.sleep(0.1)
            with open(inbox_file, "a") as f:
                f.write('{"msg": 2}\n')

        append_task = asyncio.create_task(append_message())
        result = await asyncio.wait_for(src.wait(), timeout=2.0)
        await append_task
        assert result == "a2a_message"


class TestCompositeWakeSourceCleanup:
    @pytest.mark.asyncio
    async def test_cancels_inner_tasks_on_own_cancellation(self):
        # When the composite is cancelled (e.g. the heartbeat timer wins the
        # outer race), it must cancel its inner per-source tasks rather than
        # leaking them to poll forever.
        started: list[asyncio.Task[str]] = []

        class TrackingSource:
            async def wait(self) -> str:
                try:
                    await asyncio.sleep(999)
                except asyncio.CancelledError:
                    raise
                return "never"

        src = CompositeWakeSource([TrackingSource(), TrackingSource()], timeout=999)
        task = asyncio.create_task(src.wait())
        await asyncio.sleep(0.1)
        started = list(asyncio.all_tasks())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Give the event loop a tick to finish cancelling inner tasks.
        await asyncio.sleep(0.05)
        # No leftover source-polling tasks should still be pending.
        leftover = [
            t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()
        ]
        assert leftover == []
        assert started  # sanity: tasks were actually created


class TestNudgeWakeSource:
    @pytest.mark.asyncio
    async def test_detects_new_nudge(self, tmp_path: Path):
        nudge_dir = tmp_path / "nudges"
        nudge_dir.mkdir()
        src = NudgeWakeSource(nudge_dir, poll_interval=0.05)
        await asyncio.sleep(0.1)
        src._last_count = 0

        async def add_nudge():
            await asyncio.sleep(0.1)
            (nudge_dir / "n1.json").write_text("{}")

        add_task = asyncio.create_task(add_nudge())
        result = await asyncio.wait_for(src.wait(), timeout=2.0)
        await add_task
        assert result == "nudge"


class TestHiveDaemonWakeSources:
    def test_default_wake_sources_include_a2a_and_nudge(self, tmp_path):
        from hive.config import HiveConfig, set_config
        from hive.daemon.loop import HiveDaemon
        from hive.daemon.wakeup import A2AWakeSource, NudgeWakeSource

        hive = tmp_path / ".hive"
        hive.mkdir()
        (hive / "sessions").mkdir()
        (hive / "workspaces").mkdir()
        (hive / "comms").mkdir()
        (hive / "agent_memory").mkdir()
        cfg = HiveConfig()
        cfg.economy.enabled = False
        set_config(cfg)
        cfg.save(hive)

        daemon = HiveDaemon(hive, heartbeat=60, logs_dir=tmp_path / "logs")
        assert any(isinstance(s, A2AWakeSource) for s in daemon._wake_sources)
        assert any(isinstance(s, NudgeWakeSource) for s in daemon._wake_sources)

    def test_touch_nudge_wake_file_creates_marker(self, tmp_path):
        hive = tmp_path / ".hive"
        path = touch_nudge_wake_file(hive, "nudge-abc123")
        assert path.exists()
        assert path.parent.name == "nudges"
