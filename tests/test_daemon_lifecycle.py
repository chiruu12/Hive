"""Daemon lifecycle robustness — shutdown always runs, cycle errors stay isolated."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from hive.agents.state import AgentState, AgentStatus
from hive.checkpoint import CheckpointManager
from hive.config import HiveConfig, set_config
from hive.daemon.loop import HiveDaemon
from hive.memory.store import HiveStore


@pytest.fixture
def hive_dir(tmp_path: Path) -> Path:
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

    return hive


async def _seed_agent(store: HiveStore, name: str) -> AgentState:
    state = AgentState(
        agent_id=f"{name}-test0001",
        name=name,
        role="test agent",
        model="mock-model",
        status=AgentStatus.IDLE,
        workspace=".",
    )
    await store.save_agent(state)
    return state


class TestShutdownAlwaysRuns:
    @pytest.mark.asyncio
    async def test_shutdown_on_cancellation(self, hive_dir: Path) -> None:
        """Cancelling the daemon task still writes shutdown checkpoints."""
        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        agent = await _seed_agent(store, "sleeper")

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")
        entered_run = asyncio.Event()

        async def _hang(max_cycles: int | None = None) -> None:
            entered_run.set()
            await asyncio.Event().wait()

        daemon._run = _hang  # type: ignore[assignment]

        task = asyncio.create_task(daemon.start())
        await asyncio.wait_for(entered_run.wait(), timeout=10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        cps = CheckpointManager(hive_dir).list_checkpoints(agent.agent_id)
        assert cps and cps[0].label == "daemon_shutdown"
        # Alarm task was torn down, not orphaned.
        assert daemon._alarm_task.done()

    @pytest.mark.asyncio
    async def test_shutdown_on_run_exception(self, hive_dir: Path) -> None:
        """An exception escaping _run still triggers _shutdown."""
        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        agent = await _seed_agent(store, "crasher")

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")

        async def _boom(max_cycles: int | None = None) -> None:
            raise RuntimeError("heartbeat blew up")

        daemon._run = _boom  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match="heartbeat blew up"):
            await daemon.start()

        cps = CheckpointManager(hive_dir).list_checkpoints(agent.agent_id)
        assert cps and cps[0].label == "daemon_shutdown"
        assert daemon._alarm_task.done()


class TestCycleErrorIsolation:
    @pytest.mark.asyncio
    async def test_store_failure_in_error_handler_spares_siblings(self, hive_dir: Path) -> None:
        """A store that fails while recording an agent's error must not kill the
        heartbeat for sibling agents (the gather must never see an exception)."""
        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        bad = await _seed_agent(store, "failing")
        good = await _seed_agent(store, "healthy")

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")

        async def fake_cycle(agent: AgentState) -> str:
            if agent.agent_id == bad.agent_id:
                raise RuntimeError("cycle blew up")
            return "completed"

        daemon._run_agent_cycle = fake_cycle  # type: ignore[assignment]

        async def failing_update(agent_id: str, status: AgentStatus, error: str = "") -> None:
            raise RuntimeError("db locked")

        daemon._store.update_agent_status = failing_update  # type: ignore[assignment]

        sem = asyncio.Semaphore(2)
        results = await asyncio.gather(
            daemon._run_agent_cycle_guarded(bad, 0, sem),
            daemon._run_agent_cycle_guarded(good, 0, sem),
        )
        assert results == [None, "completed"]

    @pytest.mark.asyncio
    async def test_store_failure_after_timeout_spares_siblings(self, hive_dir: Path) -> None:
        """Same isolation guarantee on the timeout path."""
        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        slow = await _seed_agent(store, "slow")
        good = await _seed_agent(store, "quick")

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")

        async def fake_cycle(agent: AgentState) -> str:
            if agent.agent_id == slow.agent_id:
                await asyncio.sleep(30)
            return "completed"

        daemon._run_agent_cycle = fake_cycle  # type: ignore[assignment]

        async def failing_get(agent_id: str) -> None:
            raise RuntimeError("db locked")

        daemon._store.get_active_goal = failing_get  # type: ignore[assignment]

        sem = asyncio.Semaphore(2)
        results = await asyncio.gather(
            daemon._run_agent_cycle_guarded(slow, 1, sem),
            daemon._run_agent_cycle_guarded(good, 1, sem),
        )
        assert results == [None, "completed"]
