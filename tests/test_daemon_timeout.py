"""Tests for per-agent cycle timeout in the daemon loop."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from hive.agents.state import AgentState, AgentStatus
from hive.config import DaemonConfig, HiveConfig, set_config
from hive.memory.store import HiveStore


@pytest.fixture
async def hive_dir(tmp_dir: Any) -> Any:
    hive = tmp_dir / ".hive"
    hive.mkdir()
    return hive


@pytest.fixture
async def store(hive_dir: Any) -> HiveStore:
    s = HiveStore(hive_dir / "hive.db")
    await s.initialize()
    return s


async def _seed_agent(store: HiveStore, name: str = "hang") -> AgentState:
    state = AgentState(
        agent_id=f"{name}-agent",
        name=name,
        role="tester",
        model="mock-model",
        status=AgentStatus.IDLE,
        workspace=".",
    )
    await store.save_agent(state)
    return state


@pytest.mark.asyncio
async def test_cycle_timeout_abandons_goal(
    tmp_dir: Any, hive_dir: Any, store: HiveStore
) -> None:
    cfg = HiveConfig()
    cfg.daemon.cycle_timeout = 1
    set_config(cfg)

    agent_state = await _seed_agent(store)
    await store.save_goal("goal-1", agent_state.agent_id, "Do something slow")

    from hive.daemon.loop import HiveDaemon

    daemon = HiveDaemon(hive_dir, heartbeat=0)
    daemon._store = store

    async def _hanging_inner(agent: Any, suffering: Any) -> str:
        await asyncio.sleep(10)
        return "completed"

    with patch.object(daemon, "_run_agent_cycle_inner", side_effect=_hanging_inner):
        daemon._running = True
        daemon._cycle_count = 0

        agents = await store.list_agents()
        alive = [a for a in agents if a.is_alive()]
        assert len(alive) == 1

        agent = alive[0]
        cycle_timeout = cfg.daemon.cycle_timeout

        try:
            await asyncio.wait_for(
                daemon._run_agent_cycle(agent),
                timeout=cycle_timeout,
            )
        except TimeoutError:
            active_goal = await store.get_active_goal(agent.agent_id)
            if active_goal:
                await store.abandon_goal(active_goal["goal_id"])
            await store.update_agent_status(agent.agent_id, AgentStatus.IDLE)

    updated = await store.get_agent(agent_state.agent_id)
    assert updated is not None
    assert updated.status == AgentStatus.IDLE

    active = await store.get_active_goal(agent_state.agent_id)
    assert active is None


@pytest.mark.asyncio
async def test_cycle_timeout_zero_disables() -> None:
    cfg = HiveConfig()
    cfg.daemon.cycle_timeout = 0
    set_config(cfg)
    assert cfg.daemon.cycle_timeout == 0


def test_cycle_timeout_negative_invalid() -> None:
    with pytest.raises(ValidationError, match="cycle_timeout"):
        DaemonConfig(cycle_timeout=-1)


def test_cycle_timeout_default() -> None:
    cfg = DaemonConfig()
    assert cfg.cycle_timeout == 300
