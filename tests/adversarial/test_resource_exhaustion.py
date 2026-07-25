"""Adversarial tests: resource exhaustion and leak detection.

These tests probe for memory leaks, file descriptor leaks, and
resource exhaustion vulnerabilities.
"""

from __future__ import annotations

import asyncio
import gc
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hive.daemon.budget import BudgetTracker
from hive.daemon.wakeup import CompositeWakeSource, FileWakeSource
from hive.memory.events import EventLog
from hive.memory.semantic import SemanticMemory

# ── Wake Source Resource Leaks ───────────────────────────────────────────────


class TestWakeSourceCleanup:
    """Verify wake sources clean up properly on cancellation."""

    @pytest.mark.asyncio
    async def test_composite_cleans_up_on_cancellation(self):
        """CompositeWakeSource should cancel all inner tasks when cancelled."""
        sources = [
            FileWakeSource(Path("/tmp/nonexistent_file_1")),
            FileWakeSource(Path("/tmp/nonexistent_file_2")),
            FileWakeSource(Path("/tmp/nonexistent_file_3")),
        ]
        composite = CompositeWakeSource(sources, timeout=10.0)

        task = asyncio.create_task(composite.wait())
        await asyncio.sleep(0.1)
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

        # Give time for cleanup
        await asyncio.sleep(0.1)
        # If we get here without hanging, cleanup worked

    @pytest.mark.asyncio
    async def test_composite_handles_empty_sources(self):
        """CompositeWakeSource with no sources should return timeout."""
        composite = CompositeWakeSource([], timeout=0.1)
        result = await composite.wait()
        assert result == "timeout"

    @pytest.mark.asyncio
    async def test_wake_source_does_not_leak_tasks(self):
        """Repeated composite timeouts should not leave pending polling tasks."""

        def _wake_owned_pending() -> list[asyncio.Task[object]]:
            """Tasks whose coroutine belongs to a WakeSource implementation."""
            current = asyncio.current_task()
            owned: list[asyncio.Task[object]] = []
            for task in asyncio.all_tasks():
                if task is current or task.done():
                    continue
                coro = task.get_coro()
                qual = getattr(coro, "__qualname__", "") or ""
                mod = getattr(coro, "__module__", "") or ""
                if "WakeSource" in qual or mod.endswith("hive.daemon.wakeup"):
                    owned.append(task)
            return owned

        initial_pending = len(_wake_owned_pending())

        for _ in range(10):
            sources = [FileWakeSource(Path("/tmp/nonexistent"))]
            composite = CompositeWakeSource(sources, timeout=0.01)
            await composite.wait()
            await asyncio.sleep(0)  # yield so cancelled inner tasks finish

        await asyncio.sleep(0.1)
        gc.collect()

        final_pending = len(_wake_owned_pending())
        assert final_pending - initial_pending == 0, (
            f"wake-owned pending tasks grew by {final_pending - initial_pending} "
            f"(initial={initial_pending}, final={final_pending})"
        )

    @pytest.mark.asyncio
    async def test_composite_wake_stress_no_task_leak(self):
        """100 create/cancel cycles should not grow the task pool unbounded."""
        initial_tasks = len(asyncio.all_tasks())

        for _ in range(100):
            sources = [
                FileWakeSource(Path("/tmp/nonexistent_file_1")),
                FileWakeSource(Path("/tmp/nonexistent_file_2")),
            ]
            composite = CompositeWakeSource(sources, timeout=0.01)
            task = asyncio.create_task(composite.wait())
            await asyncio.sleep(0)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await asyncio.sleep(0.1)
        gc.collect()

        final_tasks = len(asyncio.all_tasks())
        assert final_tasks - initial_tasks < 10


# ── EventLog Resource Leaks ─────────────────────────────────────────────────


class TestEventLogExhaustion:
    """Test EventLog under heavy write load."""

    @pytest.mark.asyncio
    async def test_rapid_event_writes(self, tmp_path):
        """Writing many events rapidly should not crash."""
        from hive.memory.events import EventType, HiveEvent

        log = EventLog(tmp_path, fsync=False)

        for i in range(1000):
            event = HiveEvent(
                event_type=EventType.DAEMON_CYCLE,
                agent_id=f"agent-{i % 10}",
                session_id=f"sess-{i}",
                data={"cycle": i},
            )
            await log.append(event)

        # Verify we can replay events (no count method exists)
        sessions = await log.list_sessions("agent-0")
        assert len(sessions) > 0

    @pytest.mark.asyncio
    async def test_large_event_data(self, tmp_path):
        """Writing events with large data payloads should not crash."""
        from hive.memory.events import EventType, HiveEvent

        log = EventLog(tmp_path, fsync=False)

        # 1MB of data
        large_data = {"payload": "x" * 1_000_000}
        event = HiveEvent(
            event_type=EventType.DAEMON_CYCLE,
            agent_id="agent-1",
            session_id="sess-1",
            data=large_data,
        )
        await log.append(event)


# ── SemanticMemory Resource Limits ───────────────────────────────────────────


class TestSemanticMemoryExhaustion:
    """Test SemanticMemory under heavy load."""

    @pytest.mark.asyncio
    async def test_many_memories(self, tmp_path):
        """Storing many memories should not crash."""
        memory = SemanticMemory(tmp_path, "test-agent")

        for i in range(100):
            await memory.store(
                f"Memory {i}: " + "x" * 100,
                metadata={"type": "test", "index": i},
            )

        # Search should still work
        results = await memory.search("Memory", top_k=5)
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_large_memory_content(self, tmp_path):
        """Storing very large content should not crash."""
        memory = SemanticMemory(tmp_path, "test-agent")

        large_content = "x" * 100_000  # 100KB
        mid = await memory.store(large_content)
        assert mid is not None

        # Should be retrievable
        record = await memory.recall(mid)
        assert record is not None


# ── Budget Tracker Edge Cases ────────────────────────────────────────────────


class TestBudgetExhaustion:
    """Test budget tracker under extreme conditions."""

    @pytest.mark.asyncio
    async def test_extremely_large_spend(self):
        """Recording extremely large spend should not overflow."""
        tracker = BudgetTracker(budget_usd=1.0)

        # Python handles arbitrary precision floats
        await tracker.record(cost_usd=float("1e308"))
        assert tracker.is_exceeded()

    @pytest.mark.asyncio
    async def test_very_small_budget(self):
        """Very small budget should still work."""
        tracker = BudgetTracker(budget_usd=0.000001)

        await tracker.record(cost_usd=0.0000005)
        assert not tracker.is_exceeded()

        await tracker.record(cost_usd=0.0000005)
        assert tracker.is_exceeded()

    @pytest.mark.asyncio
    async def test_concurrent_budget_operations(self):
        """Concurrent budget operations should maintain consistency."""
        tracker = BudgetTracker(budget_usd=10.0, budget_tokens=10000)

        async def worker(n):
            for _ in range(100):
                await tracker.record(cost_usd=0.001, tokens=1)

        await asyncio.gather(*[worker(i) for i in range(10)])

        # 10 workers * 100 iterations * 0.001 USD = 1.0 USD
        assert abs(tracker.spent_usd - 1.0) < 0.01
        assert tracker.spent_tokens == 1000


# ── File Descriptor Leaks ───────────────────────────────────────────────────


class TestFileDescriptorLeaks:
    """Check for file descriptor leaks."""

    @pytest.mark.asyncio
    async def test_event_log_does_not_leak_fds(self, tmp_path):
        """Opening and closing EventLog many times should not leak FDs."""
        from hive.memory.events import EventType, HiveEvent

        initial_fds = _count_open_fds()
        if initial_fds is None:
            pytest.skip("Open FD counting unavailable on this platform")

        for _ in range(50):
            log = EventLog(tmp_path, fsync=False)
            event = HiveEvent(
                event_type=EventType.DAEMON_CYCLE,
                agent_id="agent-1",
                session_id="sess-1",
                data={"test": True},
            )
            await log.append(event)
            del log

        gc.collect()
        final_fds = _count_open_fds()
        assert final_fds is not None

        # Allow some slack
        assert final_fds - initial_fds < 10


def _count_open_fds() -> int | None:
    """Count open file descriptors. Returns None when the platform cannot be measured."""
    fd_dir = f"/proc/{os.getpid()}/fd"
    try:
        return len(os.listdir(fd_dir))
    except (FileNotFoundError, OSError):
        pass

    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["lsof", "-p", str(os.getpid())],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if result.returncode != 0:
                return None
            lines = [line for line in result.stdout.splitlines() if line.strip()]
            # First line is the header; remaining lines are open descriptors.
            return max(0, len(lines) - 1)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None

    return None
