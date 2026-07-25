"""Tests for the goal strategy protocol."""

from __future__ import annotations

import pytest

from hive.agents.goal_strategy import GeneratedGoal, GoalContext, GoalStrategy
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

    def __init__(self, objective: str = "Do the thing", cost_usd: float = 0.0, tokens: int = 0):
        self._objective = objective
        self._cost_usd = cost_usd
        self._tokens = tokens

    async def generate_goal(self, context: GoalContext) -> GeneratedGoal:
        return GeneratedGoal(
            objective=self._objective,
            cost_usd=self._cost_usd,
            tokens=self._tokens,
        )


class NullGoalStrategy:
    """Never generates a goal but may still report spend."""

    def __init__(self, cost_usd: float = 0.0, tokens: int = 0):
        self._cost_usd = cost_usd
        self._tokens = tokens

    async def generate_goal(self, context: GoalContext) -> GeneratedGoal:
        return GeneratedGoal(objective=None, cost_usd=self._cost_usd, tokens=self._tokens)


class ContextAwareStrategy:
    """Generates goal based on context."""

    async def generate_goal(self, context: GoalContext) -> GeneratedGoal:
        if context.suffering.cumulative_load > 0.5:
            return GeneratedGoal(objective="Address suffering")
        if context.nudges:
            return GeneratedGoal(objective=f"Respond to: {context.nudges[0]}")
        return GeneratedGoal(objective=None)


def test_fixed_strategy_satisfies_protocol():
    assert isinstance(FixedGoalStrategy(), GoalStrategy)


def test_null_strategy_satisfies_protocol():
    assert isinstance(NullGoalStrategy(), GoalStrategy)


@pytest.mark.asyncio
async def test_fixed_strategy_returns_goal():
    strategy = FixedGoalStrategy("Build a website", cost_usd=0.02, tokens=30)
    ctx = _make_context()
    result = await strategy.generate_goal(ctx)
    assert result.objective == "Build a website"
    assert result.cost_usd == 0.02
    assert result.tokens == 30


@pytest.mark.asyncio
async def test_null_strategy_returns_no_objective():
    strategy = NullGoalStrategy(cost_usd=0.01, tokens=12)
    ctx = _make_context()
    result = await strategy.generate_goal(ctx)
    assert result.objective is None
    assert result.cost_usd == 0.01
    assert result.tokens == 12


@pytest.mark.asyncio
async def test_context_aware_strategy_suffering():
    from hive.agents.suffering import StressorType

    strategy = ContextAwareStrategy()
    suffering = SufferingState(agent_id="test")
    suffering.add_stressor(StressorType.FUTILITY, "stuck", "finish", initial_severity=0.6)
    ctx = _make_context(suffering=suffering)
    result = await strategy.generate_goal(ctx)
    assert result.objective is not None
    assert "suffering" in result.objective.lower()


@pytest.mark.asyncio
async def test_context_aware_strategy_nudges():
    strategy = ContextAwareStrategy()
    ctx = _make_context(nudges=["Please write tests"])
    result = await strategy.generate_goal(ctx)
    assert result.objective is not None
    assert "write tests" in result.objective.lower()


@pytest.mark.asyncio
async def test_context_aware_strategy_idle():
    strategy = ContextAwareStrategy()
    ctx = _make_context()
    result = await strategy.generate_goal(ctx)
    assert result.objective is None


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


def test_generated_goal_dataclass():
    g = GeneratedGoal(objective="Do X", cost_usd=0.05, tokens=100)
    assert g.objective == "Do X"
    assert g.cost_usd == 0.05
    assert g.tokens == 100


def test_generated_goal_defaults():
    g = GeneratedGoal(objective=None)
    assert g.objective is None
    assert g.cost_usd == 0.0
    assert g.tokens == 0
