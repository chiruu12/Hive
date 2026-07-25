"""Shared goal validation and persistence for daemon goal generation."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from hive.logging.models import GoalLog
from hive.memory.events import EventType, HiveEvent

if TYPE_CHECKING:
    from hive.agents.goal_strategy import GeneratedGoal
    from hive.logging.writer import LogWriter
    from hive.memory.events import EventLog
    from hive.memory.store import HiveStore

logger = logging.getLogger(__name__)


def generation_spend_from_result(
    *,
    cost_usd: float | None,
    input_tokens: int,
    output_tokens: int,
    objective: str | None = None,
) -> GeneratedGoal:
    """Build :class:`GeneratedGoal` spend metadata from an LLM result."""
    from hive.agents.goal_strategy import GeneratedGoal

    return GeneratedGoal(
        objective=objective,
        cost_usd=cost_usd or 0.0,
        tokens=input_tokens + output_tokens,
    )


def validate_goal(goal_text: str, recent_goals: list[dict[str, Any]]) -> str | None:
    """Return rejection reason if goal is invalid, None if acceptable."""
    if len(goal_text) < 10:
        return "too short (< 10 chars)"
    if len(goal_text) > 500:
        return "too long (> 500 chars)"

    goal_lower = goal_text.lower()
    for g in recent_goals:
        prev = g.get("objective", "").lower()
        if not prev:
            continue
        if g.get("status") in ("abandoned", "active") and prev == goal_lower:
            return f"duplicate of recent goal: {prev[:60]}"
        words_new = set(goal_lower.split())
        words_old = set(prev.split())
        if words_old and words_new:
            overlap = len(words_new & words_old) / max(len(words_new), len(words_old))
            if overlap > 0.8 and g.get("status") == "abandoned":
                return f"too similar to recently abandoned goal ({overlap:.0%} overlap)"

    return None


async def save_generated_goal(
    *,
    agent_id: str,
    objective: str,
    store: HiveStore,
    recent_goals: list[dict[str, Any]] | None = None,
    validate: bool = True,
    reasoning: str | None = None,
    log_writer: LogWriter | None = None,
    event_log: EventLog | None = None,
    session_id: str = "",
    on_saved: Callable[[str, str], Awaitable[None]] | None = None,
) -> str | None:
    """Validate and persist a generated goal.

    Returns the new ``goal_id`` when saved, or ``None`` if validation failed or
    an active goal already exists.
    """
    if recent_goals is None:
        recent_goals = await store.list_agent_goals(agent_id, limit=5)

    if validate:
        rejection = validate_goal(objective, recent_goals)
        if rejection:
            logger.info("Goal rejected for %s: %s", agent_id, rejection)
            return None

    if await store.get_active_goal(agent_id) is not None:
        logger.info(
            "Skipping generated goal for %s: an active goal already exists",
            agent_id,
        )
        return None

    goal_id = f"goal-{uuid4().hex[:8]}"
    await store.save_goal(goal_id, agent_id, objective)

    if log_writer:
        log_writer.log_goal(
            GoalLog(
                agent_id=agent_id,
                goal_id=goal_id,
                event="generated",
                objective=objective,
                reasoning=reasoning,
            )
        )

    if event_log is not None:
        sid = session_id or f"sess-{agent_id}"
        await event_log.append(
            HiveEvent(
                event_type=EventType.GOAL_SET,
                agent_id=agent_id,
                session_id=sid,
                data={"goal_id": goal_id, "objective": objective},
            )
        )

    if on_saved is not None:
        await on_saved(goal_id, objective)

    return goal_id
