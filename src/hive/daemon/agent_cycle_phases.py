"""Six-phase agent cycle bodies for the daemon heartbeat."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from hive.agents.approval import ApprovalPolicy, StoreApprovalGate
from hive.agents.existence import ExistenceLoop
from hive.agents.goal_persistence import save_generated_goal
from hive.agents.goal_strategy import GoalContext
from hive.agents.mood import MoodRegistry
from hive.agents.state import AgentState, AgentStatus
from hive.agents.suffering import assess_conditions
from hive.config import get_config
from hive.daemon import agent_cycle_outcomes as outcomes
from hive.daemon.phase import CyclePhase
from hive.logging.models import SufferingLog
from hive.memory.events import EventType
from hive.memory.pursuit_transcript import PursuitTranscriptStore
from hive.memory.recall import recall_snippets
from hive.runtime import Agent, DaemonAgentAdapter
from hive.runtime.guardrails import sanitize_inter_agent_content, sanitize_operator_nudge
from hive.runtime.memory import PersistentMemory

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from hive.daemon.agent_cycle_runner import AgentCycleRunner


async def run_inner(runner: AgentCycleRunner, agent: AgentState, suffering: Any) -> str:
    aid = agent.agent_id

    # ── Phase 1: Approval Gate ──────────────────────────────────────
    if not await runner._enter_phase(CyclePhase.APPROVAL_GATE, aid):
        return "guarded"
    try:
        approval_cfg = get_config().approval
        if approval_cfg.enabled and agent.status == AgentStatus.WAITING:
            if approval_cfg.timeout_cycles > 0:
                cutoff = (
                    datetime.now(UTC)
                    - timedelta(seconds=approval_cfg.timeout_cycles * runner._d._heartbeat)
                ).isoformat()
                await runner._d._store.expire_approvals(aid, cutoff)
            if await runner._d._store.get_pending_approvals(aid):
                return "waiting_approval"
    finally:
        await runner._exit_phase(CyclePhase.APPROVAL_GATE, aid)

    # ── Phase 2: Suffering Escalation ───────────────────────────────
    if not await runner._enter_phase(CyclePhase.SUFFERING_ESCALATION, aid):
        return "guarded"
    try:
        prev_stressors = {s.type for s in suffering.active}
        suffering.escalate_all()
        result = "idle"

        if suffering.in_crisis:
            runner._d._crisis_counts[aid] = runner._d._crisis_counts.get(aid, 0) + 1
            if runner._d._crisis_counts[aid] >= get_config().suffering.crisis_reset_after:
                suffering.force_reset("3+ consecutive crisis cycles")
                runner._d._crisis_counts[aid] = 0
        else:
            runner._d._crisis_counts[aid] = 0
    finally:
        await runner._exit_phase(CyclePhase.SUFFERING_ESCALATION, aid)

    # ── Phase 3: Context Assembly ───────────────────────────────────
    if not await runner._enter_phase(CyclePhase.CONTEXT_ASSEMBLY, aid):
        return "guarded"
    try:
        runtime_provider = runner._ctx.get_provider(agent)
        profile = runner._ctx.load_profile(agent.name)
        session_id = f"sess-{aid}"
        identity = runner._d._identity.load_or_create(aid, profile)
        memory = runner._ctx.get_memory(aid)
        persona = runner._ctx.get_persona(aid, profile)

        if persona is not None:
            persona.suffering = suffering
            persona.apply_suffering_effects()

        active_goal = await runner._d._store.get_active_goal(aid)
    finally:
        await runner._exit_phase(CyclePhase.CONTEXT_ASSEMBLY, aid)

    # ── Phase 4/5: Goal Pursuit or Goal Generation ─────────────────
    if active_goal:
        result = await phase_goal_pursuit(
            runner,
            agent=agent,
            active_goal=active_goal,
            suffering=suffering,
            approval_cfg=approval_cfg,
            runtime_provider=runtime_provider,
            profile=profile,
            session_id=session_id,
            identity=identity,
            memory=memory,
            persona=persona,
        )
    else:
        result = await phase_goal_generation(
            runner,
            agent=agent,
            suffering=suffering,
            runtime_provider=runtime_provider,
            profile=profile,
            session_id=session_id,
            persona=persona,
            memory=memory,
        )

    # ── Phase 6: Cleanup ───────────────────────────────────────────
    if not await runner._enter_phase(CyclePhase.CLEANUP, aid):
        return "guarded"
    current_stressors = {s.type for s in suffering.active}
    events = []
    for s in current_stressors - prev_stressors:
        events.append(f"added:{s}")
    for s in prev_stressors - current_stressors:
        events.append(f"resolved:{s}")
    if suffering.cumulative_load > 0:
        events.append(f"escalated:load={suffering.cumulative_load:.2f}")

    runner._d._log.log_suffering(
        SufferingLog(
            agent_id=agent.agent_id,
            cycle=runner._d._cycle_count,
            cumulative_load=suffering.cumulative_load,
            active_stressors=[s.model_dump() for s in suffering.active],
            events=events,
        )
    )

    await runner._ctx.emit(
        agent.agent_id,
        session_id,
        EventType.SUFFERING_CHANGED,
        {
            "load": suffering.cumulative_load,
            "active_count": len(suffering.active),
            "stressors": [s.type for s in suffering.active],
        },
    )
    await runner._exit_phase(CyclePhase.CLEANUP, aid)
    return result


async def phase_goal_pursuit(
    runner: AgentCycleRunner,
    *,
    agent: AgentState,
    active_goal: dict[str, Any],
    suffering: Any,
    approval_cfg: Any,
    runtime_provider: Any,
    profile: Any,
    session_id: str,
    identity: Any,
    memory: Any,
    persona: Any,
) -> str:
    aid = agent.agent_id
    if not await runner._enter_phase(CyclePhase.GOAL_PURSUIT, aid):
        return "guarded"
    await runner._d._store.update_agent_status(agent.agent_id, AgentStatus.WORKING)
    tool_timeout = get_config().daemon.tool_timeout
    approval_gate = None
    if approval_cfg.enabled:
        approval_gate = StoreApprovalGate(
            runner._d._store,
            ApprovalPolicy(approval_cfg),
            agent.agent_id,
            cycle_provider=lambda: runner._d._cycle_count,
            session_id=session_id,
            goal_id=active_goal["goal_id"],
        )
    guardrails = runner._d._guardrails
    persistent_memory = PersistentMemory(
        agent_name=aid,
        hive_dir=runner._d._hive_dir,
        semantic=memory,
    )
    if persona is not None:
        runtime_agent = Agent(
            name=agent.name,
            model=runtime_provider,
            persona=persona,
            toolkits=runner._d._build_toolkits(agent.agent_id, is_sub_agent=bool(agent.spawned_by)),
            tool_timeout=tool_timeout,
            approval_gate=approval_gate,
            guardrails=guardrails,
            log_writer=runner._d._log,
            agent_id=agent.agent_id,
            goal_id=active_goal["goal_id"],
            memory=persistent_memory,
            max_steps=profile.max_steps,
            temperature=profile.temperature,
            max_cost_usd=profile.max_cost_usd,
            max_tokens=profile.max_tokens,
        )
    else:
        runtime_agent = Agent(
            name=agent.name,
            model=runtime_provider,
            system_prompt=profile.build_system_prompt(
                economy_enabled=runner._d._economy_enabled,
            ),
            toolkits=runner._d._build_toolkits(agent.agent_id, is_sub_agent=bool(agent.spawned_by)),
            tool_timeout=tool_timeout,
            approval_gate=approval_gate,
            guardrails=guardrails,
            log_writer=runner._d._log,
            agent_id=agent.agent_id,
            goal_id=active_goal["goal_id"],
            memory=persistent_memory,
            max_steps=profile.max_steps,
            temperature=profile.temperature,
            max_cost_usd=profile.max_cost_usd,
            max_tokens=profile.max_tokens,
        )
    adapter = DaemonAgentAdapter(runtime_agent, agent.agent_id)
    mood_line = ""
    if persona is not None and not suffering.in_crisis:
        mood = MoodRegistry.default().derive(
            persona.happiness, suffering.cumulative_load, suffering.in_crisis
        )
        mood_line = mood.prompt_line()
    pursuit_context = "\n\n".join(
        p
        for p in (
            runner._d._identity.render_preamble(identity),
            mood_line,
            suffering.prompt_fragment(),
        )
        if p
    )
    est_usd, est_tokens = runner._reserve_estimates(CyclePhase.GOAL_PURSUIT)
    reservation = await runner._d._budget.reserve(est_usd, est_tokens)
    if reservation is None:
        await runner._d._store.update_agent_status(agent.agent_id, AgentStatus.IDLE)
        await runner._exit_phase(CyclePhase.GOAL_PURSUIT, aid)
        return "guarded"
    try:
        daemon_cfg = get_config().daemon
        transcript_store: PursuitTranscriptStore | None = None
        if daemon_cfg.pursuit_resume:
            transcript_store = PursuitTranscriptStore(
                runner._d._store,
                max_messages=daemon_cfg.pursuit_transcript_max_messages,
            )
        outcome = await adapter.pursue_goal(
            sanitize_inter_agent_content(
                active_goal["objective"],
                runner._d._guardrails,
                agent_id=agent.agent_id,
            ),
            context=pursuit_context,
            goal_id=active_goal["goal_id"],
            resume=daemon_cfg.pursuit_resume,
            transcript_store=transcript_store,
        )
        await runner._commit_budget(reservation, outcome.cost_usd, outcome.tokens)
    except asyncio.CancelledError:
        cost_usd = runtime_agent._total_cost
        tokens = runtime_agent._total_tokens
        if cost_usd == 0.0 and tokens == 0 and not reservation.noop:
            cost_usd, tokens = reservation.usd, reservation.tokens
        await runner._commit_budget(reservation, cost_usd, tokens)
        raise
    except Exception:
        await runner._d._budget.release(reservation)
        raise

    if outcome.waiting_approval:
        await runner._d._store.update_agent_status(agent.agent_id, AgentStatus.WAITING)
        await runner._ctx.emit(
            agent.agent_id,
            session_id,
            EventType.GOAL_SET,
            {
                "goal_id": active_goal["goal_id"],
                "waiting_approval": True,
                "approval_ids": outcome.approval_ids,
            },
        )
        await runner._exit_phase(CyclePhase.GOAL_PURSUIT, aid)
        return "waiting_approval"

    goals = await runner._d._store.list_agent_goals(agent.agent_id, limit=10)
    completed = sum(1 for g in goals if g["status"] == "completed")
    failed = sum(1 for g in goals if g["status"] == "abandoned")
    assess_conditions(suffering, completed, failed, outcome.steps_done)

    max_steps_policy = get_config().daemon.max_steps_policy

    if outcome.success:
        result = await outcomes.handle_pursuit_success(
            runner,
            agent=agent,
            active_goal=active_goal,
            outcome=outcome,
            session_id=session_id,
            persona=persona,
            identity=identity,
            memory=memory,
            suffering=suffering,
        )
    elif outcome.hit_step_limit:
        result = await outcomes.handle_pursuit_step_limit(
            runner,
            agent=agent,
            active_goal=active_goal,
            outcome=outcome,
            session_id=session_id,
            persona=persona,
            max_steps_policy=max_steps_policy,
        )
    elif outcome.steps_failed > outcome.steps_done:
        result = await outcomes.handle_pursuit_abandon(
            runner,
            agent=agent,
            active_goal=active_goal,
            outcome=outcome,
            session_id=session_id,
            persona=persona,
            record_specialization=True,
        )
    else:
        result = await outcomes.handle_pursuit_indeterminate(
            runner,
            agent=agent,
            active_goal=active_goal,
            outcome=outcome,
            session_id=session_id,
        )

    await outcomes.check_parent_rollup(runner, active_goal["goal_id"])
    await runner._d._store.update_agent_status(agent.agent_id, AgentStatus.IDLE)
    await runner._exit_phase(CyclePhase.GOAL_PURSUIT, aid)
    return result


async def phase_goal_generation(
    runner: AgentCycleRunner,
    *,
    agent: AgentState,
    suffering: Any,
    runtime_provider: Any,
    profile: Any,
    session_id: str,
    persona: Any,
    memory: Any,
) -> str:
    aid = agent.agent_id
    if not await runner._enter_phase(CyclePhase.GOAL_GENERATION, aid):
        return "guarded"
    due = await runner._d._store.get_due_schedules(agent.agent_id, runner._d._cycle_count)
    if due:
        sched = due[0]
        goal_id = f"goal-{uuid4().hex[:8]}"
        objective = sanitize_inter_agent_content(
            sched["objective"],
            runner._d._guardrails,
            agent_id=agent.agent_id,
        )
        await runner._d._store.save_goal(goal_id, agent.agent_id, objective)
        await runner._d._store.fire_schedule(sched["schedule_id"], runner._d._cycle_count)
        logger.info(
            "Fired scheduled goal for %s: %s",
            agent.agent_id,
            objective[:60],
        )
        await runner._exit_phase(CyclePhase.GOAL_GENERATION, aid)
        return "idle"

    nudges = await runner._d._store.get_pending_nudges(agent.agent_id)
    nudges = [
        sanitize_operator_nudge(n, runner._d._guardrails, agent_id=agent.agent_id) for n in nudges
    ]
    peers = await runner._ctx.get_peer_summaries(agent.agent_id)

    world_status = ""
    if runner._d._economy_enabled and runner._d._ctx.world is not None:
        world_status = runner._d._ctx.world.get_status(agent.agent_id)

    agent_stats = runner._d._stats.get(agent.agent_id) if runner._d._stats else None
    notepad_content = runner._d._notepad.get_tail(agent.agent_id)

    pending_a2a = await runner._d._a2a_store.get_pending_requests(agent.agent_id, limit=3)
    if pending_a2a:
        a2a_lines = []
        for m in pending_a2a:
            subject = sanitize_inter_agent_content(
                m.subject,
                runner._d._guardrails,
                agent_id=agent.agent_id,
            )
            a2a_lines.append(f"- [{m.type}] from {m.from_agent}: {subject}")
        a2a_context = "\n".join(a2a_lines)
        nudges.append(f"You have pending A2A messages:\n{a2a_context}")

    recent_goals = await runner._d._store.list_agent_goals(agent.agent_id, limit=5)

    memory_query = profile.role or agent.name
    if recent_goals:
        memory_query = f"{memory_query} {recent_goals[0].get('objective', '')[:80]}"
    memory_snippets = await recall_snippets(memory, memory_query, limit=3)

    est_usd, est_tokens = runner._reserve_estimates(CyclePhase.GOAL_GENERATION)
    reservation = await runner._d._budget.reserve(est_usd, est_tokens)
    if reservation is None:
        await runner._exit_phase(CyclePhase.GOAL_GENERATION, aid)
        return "guarded"

    try:
        if runner._d._goal_strategy is not None:
            ctx = GoalContext(
                agent_id=agent.agent_id,
                profile=profile,
                persona=persona,
                suffering=suffering,
                peer_summaries=peers,
                nudges=nudges,
                recent_goals=recent_goals,
                tools_description=runner._d._build_tools_description(
                    agent.agent_id, is_sub_agent=bool(agent.spawned_by)
                ),
                world_status=world_status,
                notepad_content=notepad_content,
                economy_enabled=runner._d._economy_enabled,
                agent_stats=agent_stats,
                memory_snippets=memory_snippets,
            )
            generated = await runner._d._goal_strategy.generate_goal(ctx)
            strategy_skip_validation = ctx.skip_validation or bool(
                getattr(runner._d._goal_strategy, "skip_validation", False)
            )
        else:
            strategy_skip_validation = False
            existence = ExistenceLoop(
                agent_id=agent.agent_id,
                profile=profile,
                provider=runtime_provider,
                store=runner._d._store,
                event_log=runner._d._events,
                hive_dir=runner._d._hive_dir,
                log_writer=runner._d._log,
                session_id=session_id,
                economy_enabled=runner._d._economy_enabled,
                tools_description=runner._d._build_tools_description(
                    agent.agent_id, is_sub_agent=bool(agent.spawned_by)
                ),
                world_status=world_status,
                notepad_content=notepad_content,
                persona=persona,
                stats=agent_stats,
            )
            generated = await existence.generate_goal(
                suffering,
                peers,
                nudges,
                memory_snippets=memory_snippets,
                persist=False,
            )
        await runner._commit_budget(reservation, generated.cost_usd, generated.tokens)
    except asyncio.CancelledError:
        cancel_usd = reservation.usd if not reservation.noop else 0.0
        cancel_tokens = reservation.tokens if not reservation.noop else 0
        await runner._commit_budget(reservation, cancel_usd, cancel_tokens)
        raise
    except Exception:
        await runner._d._budget.release(reservation)
        raise

    goal = generated.objective
    if runner._d._budget_exceeded or runner._d._budget.is_exceeded():
        await runner._exit_phase(CyclePhase.GOAL_GENERATION, aid)
        return "guarded"

    if goal:

        async def _on_saved(gid: str, objective: str) -> None:
            await runner._d._hooks.emit(
                "goal_generated",
                agent_id=agent.agent_id,
                goal_id=gid,
                objective=objective,
            )

        saved_id = await save_generated_goal(
            agent_id=agent.agent_id,
            objective=goal,
            store=runner._d._store,
            recent_goals=recent_goals,
            validate=not strategy_skip_validation,
            log_writer=runner._d._log,
            event_log=runner._d._events,
            session_id=session_id,
            on_saved=_on_saved,
        )
        if saved_id is None:
            goal = None

    await runner._ctx.emit(
        agent.agent_id,
        session_id,
        EventType.EXISTENCE_CYCLE,
        {"goal_generated": goal or "none", "suffering_load": suffering.cumulative_load},
    )
    await runner._exit_phase(CyclePhase.GOAL_GENERATION, aid)
    return "idle"
