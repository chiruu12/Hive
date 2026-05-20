"""Tests for the goal strategy protocol."""

from __future__ import annotations

from uuid import uuid4

import pytest

from hive.agents.goal_strategy import Goal, GoalContext, GoalStrategy
from hive.agents.profile import AgentProfile
from hive.agents.suffering import SufferingState


def _make_context(**overrides) -> GoalContext:
    defaults = {
        "agent_id": "test-agent",
        "profile": AgentProfile(name="tester", role="test role"),
        "persona": None,
        "suffering": SufferingState(agent_id="test-agent"),
        "peer_summaries": [],
        "nudges": [],
        "recent_goals": [],
    }
    defaults.update(overrides)
    return GoalContext(**defaults)


class FixedGoalStrategy:
    """Always returns the same goal."""

    def __init__(self, objective: str = "Do the thing"):
        self._objective = objective

    async def generate_goal(self, context: GoalContext) -> Goal | None:
        return Goal(
            goal_id=f"goal-{uuid4().hex[:8]}",
            objective=self._objective,
            reasoning="Because I said so",
        )


class NullGoalStrategy:
    """Never generates a goal."""

    async def generate_goal(self, context: GoalContext) -> Goal | None:
        return None


class ContextAwareStrategy:
    """Generates goal based on context."""

    async def generate_goal(self, context: GoalContext) -> Goal | None:
        if context.suffering.cumulative_load > 0.5:
            return Goal(
                goal_id=f"goal-{uuid4().hex[:8]}",
                objective="Address suffering",
            )
        if context.nudges:
            return Goal(
                goal_id=f"goal-{uuid4().hex[:8]}",
                objective=f"Respond to: {context.nudges[0]}",
            )
        return None


def test_fixed_strategy_satisfies_protocol():
    assert isinstance(FixedGoalStrategy(), GoalStrategy)


def test_null_strategy_satisfies_protocol():
    assert isinstance(NullGoalStrategy(), GoalStrategy)


@pytest.mark.asyncio
async def test_fixed_strategy_returns_goal():
    strategy = FixedGoalStrategy("Build a website")
    ctx = _make_context()
    goal = await strategy.generate_goal(ctx)
    assert goal is not None
    assert goal.objective == "Build a website"
    assert goal.reasoning == "Because I said so"
    assert goal.goal_id.startswith("goal-")


@pytest.mark.asyncio
async def test_null_strategy_returns_none():
    strategy = NullGoalStrategy()
    ctx = _make_context()
    goal = await strategy.generate_goal(ctx)
    assert goal is None


@pytest.mark.asyncio
async def test_context_aware_strategy_suffering():
    from hive.agents.suffering import StressorType

    strategy = ContextAwareStrategy()
    suffering = SufferingState(agent_id="test")
    suffering.add_stressor(StressorType.FUTILITY, "stuck", "finish", initial_severity=0.6)
    ctx = _make_context(suffering=suffering)
    goal = await strategy.generate_goal(ctx)
    assert goal is not None
    assert "suffering" in goal.objective.lower()


@pytest.mark.asyncio
async def test_context_aware_strategy_nudges():
    strategy = ContextAwareStrategy()
    ctx = _make_context(nudges=["Please write tests"])
    goal = await strategy.generate_goal(ctx)
    assert goal is not None
    assert "write tests" in goal.objective.lower()


@pytest.mark.asyncio
async def test_context_aware_strategy_idle():
    strategy = ContextAwareStrategy()
    ctx = _make_context()
    goal = await strategy.generate_goal(ctx)
    assert goal is None


def test_goal_context_has_all_fields():
    ctx = _make_context(
        tools_description="tool1, tool2",
        world_status="employed",
        notepad_content="notes here",
        economy_enabled=False,
    )
    assert ctx.agent_id == "test-agent"
    assert ctx.tools_description == "tool1, tool2"
    assert ctx.world_status == "employed"
    assert ctx.notepad_content == "notes here"
    assert ctx.economy_enabled is False
    assert ctx.extra == {}


def test_goal_dataclass():
    g = Goal(goal_id="g1", objective="Do X", reasoning="Because Y")
    assert g.goal_id == "g1"
    assert g.objective == "Do X"
    assert g.reasoning == "Because Y"


def test_goal_default_reasoning():
    g = Goal(goal_id="g2", objective="Do Z")
    assert g.reasoning is None
