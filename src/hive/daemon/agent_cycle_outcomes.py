"""Goal pursuit outcome handling for the agent cycle."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from hive.logging.models import GoalLog
from hive.memory.events import EventType
from hive.memory.goals import GoalEngine
from hive.runtime.bridge import GoalOutcome

if TYPE_CHECKING:
    from hive.agents.state import AgentState
    from hive.daemon.agent_cycle_runner import AgentCycleRunner

logger = logging.getLogger(__name__)


async def handle_pursuit_success(
    runner: AgentCycleRunner,
    *,
    agent: AgentState,
    active_goal: dict[str, Any],
    outcome: GoalOutcome,
    session_id: str,
    persona: Any,
    identity: Any,
    memory: Any,
    suffering: Any,
) -> str:
    d = runner._d
    ctx = runner._ctx
    await d._store.complete_goal(active_goal["goal_id"])
    d._log.log_goal(
        GoalLog(
            agent_id=agent.agent_id,
            goal_id=active_goal["goal_id"],
            event="completed",
            objective=active_goal["objective"],
            outcome_summary=outcome.summary,
            steps_done=outcome.steps_done,
            steps_failed=outcome.steps_failed,
        )
    )
    await ctx.emit(
        agent.agent_id,
        session_id,
        EventType.GOAL_COMPLETED,
        {"goal_id": active_goal["goal_id"], "summary": outcome.summary},
    )
    await d._hooks.emit("goal_completed", agent_id=agent.agent_id, goal_id=active_goal["goal_id"])
    if persona is not None:
        persona.update_from_event("goal_completed", outcome.summary)
    d._identity.update_narrative(
        agent.agent_id,
        active_goal["objective"],
        outcome.summary,
    )
    await memory.store(
        f"Completed goal: {active_goal['objective']}. {outcome.summary}",
        metadata={"type": "goal_completed", "goal_id": active_goal["goal_id"]},
    )
    goals_snap = await d._store.list_agent_goals(agent.agent_id, limit=10)
    identity = d._identity.load(agent.agent_id) or identity
    d._checkpoint.save(
        agent.agent_id,
        "goal_completed",
        suffering,
        identity,
        d._ctx,
        goals_snap,
        persona_snapshot=persona.snapshot() if persona else None,
    )
    d._specialization.record(
        agent.agent_id,
        "goal_pursuit",
        True,
        0,
        "autonomy_loop",
    )
    if agent.spawned_by:
        await d._store.complete_sub_agent(agent.agent_id, outcome.summary)
    return "completed"


async def handle_pursuit_step_limit(
    runner: AgentCycleRunner,
    *,
    agent: AgentState,
    active_goal: dict[str, Any],
    outcome: GoalOutcome,
    session_id: str,
    persona: Any,
    max_steps_policy: str,
) -> str:
    d = runner._d
    ctx = runner._ctx
    if max_steps_policy == "abandon":
        await d._store.abandon_goal(active_goal["goal_id"])
        d._log.log_goal(
            GoalLog(
                agent_id=agent.agent_id,
                goal_id=active_goal["goal_id"],
                event="abandoned",
                objective=active_goal["objective"],
                outcome_summary=outcome.summary,
                steps_done=outcome.steps_done,
                steps_failed=outcome.steps_failed,
            )
        )
        await ctx.emit(
            agent.agent_id,
            session_id,
            EventType.GOAL_ABANDONED,
            {
                "goal_id": active_goal["goal_id"],
                "reason": f"max_steps ({max_steps_policy}): {outcome.summary}",
            },
        )
        await d._hooks.emit(
            "goal_abandoned",
            agent_id=agent.agent_id,
            goal_id=active_goal["goal_id"],
        )
        d._identity.update_narrative(
            agent.agent_id,
            active_goal["objective"],
            f"Abandoned (step limit): {outcome.summary}",
        )
        if persona is not None:
            persona.update_from_event("goal_abandoned", outcome.summary)
        return "abandoned"

    await d._store.update_goal_progress(
        active_goal["goal_id"],
        outcome.steps_done,
        outcome.steps_failed,
    )
    d._log.log_goal(
        GoalLog(
            agent_id=agent.agent_id,
            goal_id=active_goal["goal_id"],
            event="max_steps",
            objective=active_goal["objective"],
            outcome_summary=outcome.summary,
            steps_done=outcome.steps_done,
            steps_failed=outcome.steps_failed,
        )
    )
    await ctx.emit(
        agent.agent_id,
        session_id,
        EventType.GOAL_SET,
        {
            "goal_id": active_goal["goal_id"],
            "max_steps_reached": True,
            "steps_done": outcome.steps_done,
            "summary": outcome.summary,
        },
    )
    await d._hooks.emit(
        "goal_max_steps",
        agent_id=agent.agent_id,
        goal_id=active_goal["goal_id"],
        steps_done=outcome.steps_done,
    )
    return "max_steps"


async def handle_pursuit_abandon(
    runner: AgentCycleRunner,
    *,
    agent: AgentState,
    active_goal: dict[str, Any],
    outcome: GoalOutcome,
    session_id: str,
    persona: Any,
    record_specialization: bool,
) -> str:
    d = runner._d
    ctx = runner._ctx
    await d._store.abandon_goal(active_goal["goal_id"])
    d._log.log_goal(
        GoalLog(
            agent_id=agent.agent_id,
            goal_id=active_goal["goal_id"],
            event="abandoned",
            objective=active_goal["objective"],
            outcome_summary=outcome.summary,
            steps_done=outcome.steps_done,
            steps_failed=outcome.steps_failed,
        )
    )
    await ctx.emit(
        agent.agent_id,
        session_id,
        EventType.GOAL_ABANDONED,
        {"goal_id": active_goal["goal_id"], "reason": outcome.summary},
    )
    await d._hooks.emit("goal_abandoned", agent_id=agent.agent_id, goal_id=active_goal["goal_id"])
    d._identity.update_narrative(
        agent.agent_id,
        active_goal["objective"],
        f"Abandoned: {outcome.summary}",
    )
    if persona is not None:
        persona.update_from_event("goal_abandoned", outcome.summary)
    if record_specialization:
        d._specialization.record(
            agent.agent_id,
            "goal_pursuit",
            False,
            0,
            "autonomy_loop",
        )
    return "abandoned"


async def handle_pursuit_indeterminate(
    runner: AgentCycleRunner,
    *,
    agent: AgentState,
    active_goal: dict[str, Any],
    outcome: GoalOutcome,
    session_id: str,
) -> str:
    d = runner._d
    ctx = runner._ctx
    logger.warning(
        "Indeterminate pursuit outcome for %s goal %s: %s",
        agent.agent_id,
        active_goal["goal_id"],
        outcome.summary,
    )
    summary = outcome.summary or "indeterminate outcome"
    await d._store.abandon_goal(active_goal["goal_id"])
    d._log.log_goal(
        GoalLog(
            agent_id=agent.agent_id,
            goal_id=active_goal["goal_id"],
            event="abandoned",
            objective=active_goal["objective"],
            outcome_summary=summary,
            steps_done=outcome.steps_done,
            steps_failed=outcome.steps_failed,
        )
    )
    await ctx.emit(
        agent.agent_id,
        session_id,
        EventType.GOAL_ABANDONED,
        {"goal_id": active_goal["goal_id"], "reason": summary},
    )
    await d._hooks.emit("goal_abandoned", agent_id=agent.agent_id, goal_id=active_goal["goal_id"])
    return "abandoned"


async def check_parent_rollup(runner: AgentCycleRunner, goal_id: str) -> None:
    """If this goal has a parent, check if all subtasks are done."""
    goal_data = await runner._d._store.get_goal_by_id(goal_id)
    parent_id = goal_data.get("parent_goal_id") if goal_data else None
    if not parent_id:
        return
    ge = GoalEngine(runner._d._store)
    rollup = await ge.check_subtask_rollup(parent_id)
    if rollup == "completed":
        await runner._d._store.complete_goal(parent_id)
        logger.info("Parent goal %s completed (all subtasks done)", parent_id)
    elif rollup == "abandoned":
        await runner._d._store.abandon_goal(parent_id)
        logger.info("Parent goal %s abandoned (subtask failed)", parent_id)
