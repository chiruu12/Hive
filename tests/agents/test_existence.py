"""Tests for ExistenceLoop goal generation (single-active-goal guard)."""

from __future__ import annotations

from typing import Any

import pytest

from hive.agents.existence import ExistenceLoop
from hive.agents.profile import AgentProfile
from hive.agents.suffering import SufferingState
from hive.memory.events import EventLog
from hive.memory.store import HiveStore
from hive.runtime.types import GenerateResult, Message


class _GoalProvider:
    """Provider that always proposes a fresh goal as JSON."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate_with_metadata(self, **kwargs: Any) -> GenerateResult:
        self.calls += 1
        return GenerateResult(
            message=Message.assistant('{"goal": "Write the docs", "reasoning": "needed"}'),
            model="mock",
        )


async def _make_loop(tmp_path: Any) -> tuple[ExistenceLoop, HiveStore]:
    store = HiveStore(tmp_path / "hive.db")
    await store.initialize()
    loop = ExistenceLoop(
        agent_id="a1",
        profile=AgentProfile(name="tester", role="test"),
        provider=_GoalProvider(),
        store=store,
        event_log=EventLog(tmp_path),
        economy_enabled=False,
    )
    return loop, store


@pytest.mark.asyncio
async def test_generates_goal_when_idle(tmp_path: Any) -> None:
    loop, store = await _make_loop(tmp_path)
    goal = await loop.generate_goal(SufferingState(agent_id="a1"), [], [])
    assert goal == "Write the docs"
    assert await store.get_active_goal("a1") is not None


@pytest.mark.asyncio
async def test_skips_when_active_goal_already_exists(tmp_path: Any) -> None:
    loop, store = await _make_loop(tmp_path)
    # A goal landed (e.g. delegation/schedule) before generation finishes.
    await store.save_goal("goal-existing", "a1", "Pre-existing work")

    goal = await loop.generate_goal(SufferingState(agent_id="a1"), [], [])

    assert goal is None
    # Still exactly one active goal -- no duplicate piled on.
    active = await store.get_active_goal("a1")
    assert active is not None
    assert active["goal_id"] == "goal-existing"
