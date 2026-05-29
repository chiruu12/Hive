"""Tests for concurrent, bounded, isolated agent cycles (Phase 2 B1)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from hive.agents.state import AgentState, AgentStatus
from hive.config import HiveConfig, set_config
from hive.daemon.loop import HiveDaemon
from hive.memory.store import HiveStore


async def _seed(store: HiveStore, agent_id: str) -> None:
    await store.save_agent(
        AgentState(
            agent_id=agent_id,
            name=agent_id,
            role="tester",
            model="mock-model",
            status=AgentStatus.IDLE,
            workspace=".",
        )
    )


def _daemon(tmp_path: Path, max_concurrent: int, cycle_timeout: int = 0) -> HiveDaemon:
    # The daemon loads config in __init__, so set the global config AFTER
    # construction (read by _run at runtime) and disable economy on the instance.
    daemon = HiveDaemon(tmp_path / ".hive", heartbeat=0, logs_dir=tmp_path / "logs")
    cfg = HiveConfig()
    cfg.daemon.max_concurrent_agents = max_concurrent
    cfg.daemon.cycle_timeout = cycle_timeout
    set_config(cfg)
    daemon._economy_enabled = False  # avoid life-event provider calls
    return daemon


class TestConcurrentCycles:
    @pytest.mark.asyncio
    async def test_cycles_run_concurrently_bounded(self, tmp_path: Path) -> None:
        """All agents run; no more than max_concurrent_agents are in flight at once."""
        daemon = _daemon(tmp_path, max_concurrent=3)
        await daemon._store.initialize()
        for i in range(7):
            await _seed(daemon._store, f"a{i}")

        active = 0
        peak = 0
        ran: set[str] = set()

        async def fake_cycle(agent: AgentState) -> str:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.02)
                ran.add(agent.agent_id)
                return "completed"
            finally:
                active -= 1

        daemon._run_agent_cycle = fake_cycle  # type: ignore[method-assign]
        await daemon.start(max_cycles=1)

        assert ran == {f"a{i}" for i in range(7)}  # every agent ran
        assert peak == 3  # capped at the configured concurrency

    @pytest.mark.asyncio
    async def test_one_failing_agent_does_not_block_others(self, tmp_path: Path) -> None:
        """A raising cycle is isolated: siblings still complete, daemon survives."""
        daemon = _daemon(tmp_path, max_concurrent=8)
        await daemon._store.initialize()
        for aid in ["ok1", "boom", "ok2"]:
            await _seed(daemon._store, aid)

        ran: set[str] = set()

        async def fake_cycle(agent: AgentState) -> str:
            if agent.agent_id == "boom":
                raise RuntimeError("kaboom")
            await asyncio.sleep(0.01)
            ran.add(agent.agent_id)
            return "completed"

        daemon._run_agent_cycle = fake_cycle  # type: ignore[method-assign]
        await daemon.start(max_cycles=1)

        assert ran == {"ok1", "ok2"}  # healthy agents completed
        # The failing agent was isolated and marked ERROR.
        boom = await daemon._store.get_agent("boom")
        assert boom is not None and boom.status == AgentStatus.ERROR

    @pytest.mark.asyncio
    async def test_timeout_isolates_slow_agent(self, tmp_path: Path) -> None:
        """A timed-out cycle abandons that agent's goal and frees it; siblings finish.

        Drives the real _run_agent_cycle_guarded timeout path (not an inline copy).
        """
        daemon = _daemon(tmp_path, max_concurrent=8, cycle_timeout=1)
        await daemon._store.initialize()
        for aid in ["slow", "ok"]:
            await _seed(daemon._store, aid)
        await daemon._store.save_goal("g-slow", "slow", "a goal that will time out")

        ran: set[str] = set()

        async def fake_cycle(agent: AgentState) -> str:
            if agent.agent_id == "slow":
                await asyncio.sleep(5)  # exceeds the 1s cycle_timeout -> cancelled
                return "completed"
            ran.add(agent.agent_id)
            return "completed"

        daemon._run_agent_cycle = fake_cycle  # type: ignore[method-assign]
        await daemon.start(max_cycles=1)

        assert ran == {"ok"}  # the healthy agent completed despite the slow sibling
        slow = await daemon._store.get_agent("slow")
        assert slow is not None and slow.status == AgentStatus.IDLE  # freed, not stuck
        goal = await daemon._store.get_goal_by_id("g-slow")
        assert goal is not None and goal["status"] == "abandoned"


class TestConcurrencyConfig:
    def test_max_concurrent_agents_must_be_positive(self) -> None:
        from pydantic import ValidationError

        from hive.config import DaemonConfig

        with pytest.raises(ValidationError, match="max_concurrent_agents"):
            DaemonConfig(max_concurrent_agents=0)

    def test_max_concurrent_agents_default(self) -> None:
        from hive.config import DaemonConfig

        assert DaemonConfig().max_concurrent_agents == 8
