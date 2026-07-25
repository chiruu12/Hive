"""Tests for per-agent cycle timeout in the daemon loop."""

from __future__ import annotations

import asyncio
from typing import Any

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
async def test_cycle_timeout_abandons_goal_when_legacy_flag(
    tmp_dir: Any, hive_dir: Any, store: HiveStore
) -> None:
    cfg = HiveConfig()
    cfg.daemon.cycle_timeout = 1
    cfg.daemon.preserve_active_goals_on_timeout = False
    set_config(cfg)
    cfg.save(hive_dir)

    agent_state = await _seed_agent(store)
    await store.save_goal("goal-1", agent_state.agent_id, "Do something slow")

    from hive.daemon.loop import HiveDaemon

    daemon = HiveDaemon(hive_dir, heartbeat=0)
    daemon._store = store

    async def _hanging_cycle(agent: AgentState) -> str:
        await asyncio.sleep(10)
        return "completed"

    daemon._run_agent_cycle = _hanging_cycle  # type: ignore[method-assign]

    sem = asyncio.Semaphore(8)
    result = await daemon._cycle_runner.run_guarded(
        agent_state, cycle_timeout=cfg.daemon.cycle_timeout, sem=sem
    )

    assert result is None

    updated = await store.get_agent(agent_state.agent_id)
    assert updated is not None
    assert updated.status == AgentStatus.IDLE

    active = await store.get_active_goal(agent_state.agent_id)
    assert active is None


@pytest.mark.asyncio
async def test_cycle_timeout_preserves_goal_and_transcript(
    tmp_dir: Any, hive_dir: Any, store: HiveStore
) -> None:
    """Default policy parks on timeout without abandoning goal or transcript."""
    cfg = HiveConfig()
    cfg.daemon.cycle_timeout = 1
    cfg.daemon.preserve_active_goals_on_timeout = True
    set_config(cfg)
    cfg.save(hive_dir)

    agent_state = await _seed_agent(store)
    goal_id = "goal-timeout"
    await store.save_goal(goal_id, agent_state.agent_id, "Do something slow")

    from hive.memory.pursuit_transcript import PursuitTranscriptStore, message_to_dict
    from hive.runtime.types import Message

    transcript_store = PursuitTranscriptStore(store)
    await transcript_store.save_messages(
        goal_id,
        agent_state.agent_id,
        [Message.user("partial"), Message.assistant("working")],
    )
    before = await transcript_store.load_messages(goal_id, agent_state.agent_id)
    assert len(before) == 2

    from hive.daemon.loop import HiveDaemon

    daemon = HiveDaemon(hive_dir, heartbeat=0)
    daemon._store = store

    async def _hanging_cycle(agent: AgentState) -> str:
        await asyncio.sleep(10)
        return "completed"

    daemon._run_agent_cycle = _hanging_cycle  # type: ignore[method-assign]

    sem = asyncio.Semaphore(8)
    result = await daemon._cycle_runner.run_guarded(
        agent_state, cycle_timeout=cfg.daemon.cycle_timeout, sem=sem
    )

    assert result is None

    updated = await store.get_agent(agent_state.agent_id)
    assert updated is not None
    assert updated.status == AgentStatus.IDLE

    active = await store.get_active_goal(agent_state.agent_id)
    assert active is not None
    assert active["goal_id"] == goal_id

    after = await transcript_store.load_messages(goal_id, agent_state.agent_id)
    assert len(after) == len(before)
    assert message_to_dict(after[0]) == message_to_dict(before[0])


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
