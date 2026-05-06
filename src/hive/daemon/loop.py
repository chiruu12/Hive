"""Daemon heartbeat loop — drives all agents on a cycle."""

import asyncio
import logging
from pathlib import Path

from hive.agents.delegation import DelegationEngine
from hive.agents.existence import ExistenceLoop
from hive.agents.identity import IdentityManager
from hive.agents.loop import AgentLoop
from hive.agents.profile import AgentProfile
from hive.agents.specialization import SpecializationTracker
from hive.agents.state import AgentState, AgentStatus
from hive.agents.suffering import SufferingState, assess_conditions
from hive.agents.swarm import SwarmLearning
from hive.checkpoint import CheckpointManager
from hive.config import get_config, load_config
from hive.execution.context import ExecutionContext
from hive.execution.registry import ToolRegistry
from hive.logging.models import CycleLog, GoalLog, SufferingLog
from hive.logging.writer import LogWriter
from hive.memory.events import EventLog, EventType, HiveEvent
from hive.memory.semantic import SemanticMemory
from hive.memory.store import HiveStore
from hive.models.router import create_provider
from hive.world.event_engine import EventEngine
from hive.world.state import WorldState
from hive.world.stats import StatsManager

logger = logging.getLogger(__name__)


class HiveDaemon:
    """Main daemon that drives all agents on a heartbeat cycle."""

    def __init__(
        self,
        hive_dir: Path,
        heartbeat: int | None = None,
        logs_dir: Path | None = None,
        profiles: list[str] | None = None,
    ):
        self._hive_dir = hive_dir
        cfg = load_config(hive_dir)
        self._heartbeat = heartbeat or cfg.daemon.heartbeat
        self._running = False
        self._store = HiveStore(hive_dir / "hive.db")
        self._events = EventLog(hive_dir)

        self._ctx = ExecutionContext(
            world=WorldState(hive_dir),
            store=self._store,
            comms_dir=hive_dir / "comms",
            memory_dir=hive_dir / "agent_memory",
        )

        self._registry = ToolRegistry(self._ctx)
        self._log = LogWriter(logs_dir or (hive_dir.parent / "logs"))
        self._identity = IdentityManager(hive_dir)
        self._checkpoint = CheckpointManager(hive_dir)
        self._delegation = DelegationEngine(self._store)
        self._specialization = SpecializationTracker()
        self._swarm = SwarmLearning(self._store, self._specialization)
        self._stats = StatsManager(hive_dir)
        self._event_engine = EventEngine(self._stats, self._ctx.world)
        self._memories: dict[str, SemanticMemory] = {}
        self._suffering: dict[str, SufferingState] = {}
        self._cycle_count = 0
        self._crisis_counts: dict[str, int] = {}
        self._profiles = profiles or []

    async def start(self) -> None:
        """Initialize store, discover tools, start heartbeat."""
        await self._store.initialize()
        self._registry.discover()

        agents = await self._store.list_agents()
        agent_ids = [a.agent_id for a in agents if a.is_alive()]
        self._log.start_run(
            heartbeat=self._heartbeat,
            profiles=self._profiles,
            agents=agent_ids,
            tools=self._registry.get_tool_names(),
        )

        logger.info(
            "Daemon started: run=%s, %d tools, heartbeat=%ds",
            self._log.run_id,
            len(self._registry.list_tools()),
            self._heartbeat,
        )
        self._running = True
        await self._run()

    async def _run(self) -> None:
        goals_completed = 0
        goals_abandoned = 0

        while self._running:
            self._cycle_count += 1
            agents = await self._store.list_agents()
            alive = [a for a in agents if a.is_alive()]
            crisis_count = sum(1 for a in alive if self._get_suffering(a.agent_id).in_crisis)

            for agent in alive:
                try:
                    result = await self._run_agent_cycle(agent)
                    if result == "completed":
                        goals_completed += 1
                    elif result == "abandoned":
                        goals_abandoned += 1
                except Exception as e:
                    logger.error("Cycle failed for %s: %s", agent.agent_id, e)
                    await self._store.update_agent_status(
                        agent.agent_id, AgentStatus.ERROR, error=str(e)
                    )

            self._process_payday(alive)
            await self._process_life_events(alive)

            if self._cycle_count % 5 == 0 and alive:
                agent_ids = [a.agent_id for a in alive]
                report = await self._swarm.run_cycle(agent_ids)
                logger.info(
                    "Swarm learning cycle %d: success=%.0f%% patterns=%d recs=%d",
                    report.cycle_id,
                    report.swarm_success_rate * 100,
                    report.pattern_count,
                    len(report.recommendations),
                )

            self._log.log_cycle(
                CycleLog(
                    run_id=self._log.run_id,
                    cycle=self._cycle_count,
                    agents_active=len(alive),
                    agents_in_crisis=crisis_count,
                    goals_completed_this_cycle=goals_completed,
                    goals_abandoned_this_cycle=goals_abandoned,
                )
            )
            goals_completed = 0
            goals_abandoned = 0

            await asyncio.sleep(self._heartbeat)

    async def _run_agent_cycle(self, agent: AgentState) -> str:
        suffering = self._get_suffering(agent.agent_id)
        prev_stressors = {s.type.value for s in suffering.active}
        suffering.escalate_all()
        result = "idle"

        if suffering.in_crisis:
            self._crisis_counts[agent.agent_id] = self._crisis_counts.get(agent.agent_id, 0) + 1
            if self._crisis_counts[agent.agent_id] >= get_config().suffering.crisis_reset_after:
                suffering.force_reset("3+ consecutive crisis cycles")
                self._crisis_counts[agent.agent_id] = 0
        else:
            self._crisis_counts[agent.agent_id] = 0

        provider = create_provider(agent.model)
        profile = self._load_profile(agent.name)
        session_id = f"sess-{agent.agent_id}"
        identity = self._identity.load_or_create(agent.agent_id, profile)
        memory = self._get_memory(agent.agent_id)

        active_goal = await self._store.get_active_goal(agent.agent_id)

        if active_goal:
            await self._store.update_agent_status(agent.agent_id, AgentStatus.WORKING)
            loop = AgentLoop(
                agent_id=agent.agent_id,
                profile=profile,
                provider=provider,
                ctx=self._ctx,
                store=self._store,
                event_log=self._events,
                log_writer=self._log,
                session_id=session_id,
                goal_id=active_goal["goal_id"],
            )
            outcome = await loop.pursue_goal(
                active_goal["objective"],
                context=suffering.prompt_fragment(),
            )

            goals = await self._store.list_agent_goals(agent.agent_id, limit=10)
            completed = sum(1 for g in goals if g["status"] == "completed")
            failed = sum(1 for g in goals if g["status"] == "abandoned")
            assess_conditions(suffering, completed, failed, outcome.steps_done)

            if outcome.success:
                await self._store.complete_goal(active_goal["goal_id"])
                self._log.log_goal(
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
                await self._emit(
                    agent.agent_id,
                    session_id,
                    EventType.GOAL_COMPLETED,
                    {"goal_id": active_goal["goal_id"], "summary": outcome.summary},
                )
                result = "completed"
                self._identity.update_narrative(
                    agent.agent_id,
                    active_goal["objective"],
                    outcome.summary,
                )
                await memory.store(
                    f"Completed goal: {active_goal['objective']}. {outcome.summary}",
                    metadata={"type": "goal_completed", "goal_id": active_goal["goal_id"]},
                )
                goals_snap = await self._store.list_agent_goals(agent.agent_id, limit=10)
                self._checkpoint.save(
                    agent.agent_id,
                    "goal_completed",
                    suffering,
                    identity,
                    self._ctx,
                    goals_snap,
                )
                self._specialization.record(
                    agent.agent_id,
                    "goal_pursuit",
                    True,
                    0,
                    "autonomy_loop",
                )
            elif outcome.steps_failed > outcome.steps_done:
                await self._store.abandon_goal(active_goal["goal_id"])
                self._log.log_goal(
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
                await self._emit(
                    agent.agent_id,
                    session_id,
                    EventType.GOAL_ABANDONED,
                    {"goal_id": active_goal["goal_id"], "reason": outcome.summary},
                )
                result = "abandoned"
                self._specialization.record(
                    agent.agent_id,
                    "goal_pursuit",
                    False,
                    0,
                    "autonomy_loop",
                )

            await self._store.update_agent_status(agent.agent_id, AgentStatus.IDLE)

        else:
            nudges = await self._store.get_pending_nudges(agent.agent_id)
            peers = await self._get_peer_summaries(agent.agent_id)

            existence = ExistenceLoop(
                agent_id=agent.agent_id,
                profile=profile,
                provider=provider,
                ctx=self._ctx,
                store=self._store,
                event_log=self._events,
                log_writer=self._log,
                session_id=session_id,
            )
            goal = await existence.generate_goal(suffering, peers, nudges)

            await self._emit(
                agent.agent_id,
                session_id,
                EventType.EXISTENCE_CYCLE,
                {"goal_generated": goal or "none", "suffering_load": suffering.cumulative_load},
            )

        current_stressors = {s.type.value for s in suffering.active}
        events = []
        for s in current_stressors - prev_stressors:
            events.append(f"added:{s}")
        for s in prev_stressors - current_stressors:
            events.append(f"resolved:{s}")
        if suffering.cumulative_load > 0:
            events.append(f"escalated:load={suffering.cumulative_load:.2f}")

        self._log.log_suffering(
            SufferingLog(
                agent_id=agent.agent_id,
                cycle=self._cycle_count,
                cumulative_load=suffering.cumulative_load,
                active_stressors=[s.model_dump() for s in suffering.active],
                events=events,
            )
        )

        await self._emit(
            agent.agent_id,
            session_id,
            EventType.SUFFERING_CHANGED,
            {
                "load": suffering.cumulative_load,
                "active_count": len(suffering.active),
                "stressors": [s.type.value for s in suffering.active],
            },
        )

        return result

    def _process_payday(self, agents: list[AgentState]) -> None:
        """Auto-pay salary to employed agents each cycle."""
        for agent in agents:
            job = self._ctx.world.agent_job(agent.agent_id)
            if job:
                self._ctx.world.work(agent.agent_id)

    async def _process_life_events(self, agents: list[AgentState]) -> None:
        """Roll random life events and let agents choose via LLM."""
        for agent in agents:
            self._stats.tick(agent.agent_id)
            events = self._event_engine.roll_events(agent.agent_id, self._cycle_count)

            for event in events:
                prompt = self._event_engine.format_event_prompt(event)
                provider = create_provider(agent.model)
                profile = self._load_profile(agent.name)

                try:
                    response = await provider.complete(
                        messages=[{"role": "user", "content": prompt}],
                        system=profile.build_system_prompt(),
                        max_tokens=50,
                    )
                    choice_id = (
                        response.content.strip().lower().split()[0] if response.content else ""
                    )
                    valid_ids = {c.id for c in event.choices}
                    if choice_id not in valid_ids:
                        choice_id = event.choices[0].id
                except Exception:
                    choice_id = event.choices[0].id

                outcome = self._event_engine.apply_choice(
                    agent.agent_id,
                    event,
                    choice_id,
                    self._cycle_count,
                )

                session_id = f"sess-{agent.agent_id}"
                await self._emit(
                    agent.agent_id,
                    session_id,
                    EventType.EXISTENCE_CYCLE,
                    {
                        "life_event": event.name,
                        "choice": outcome.choice_description,
                        "stat_changes": outcome.stat_changes,
                        "follow_ups": outcome.follow_ups_triggered,
                    },
                )

                memory = self._get_memory(agent.agent_id)
                await memory.store(
                    f"Life event: {event.name}. Chose: {outcome.choice_description}",
                    metadata={"type": "life_event", "event_id": event.event_id},
                )

    def _get_suffering(self, agent_id: str) -> SufferingState:
        if agent_id not in self._suffering:
            self._suffering[agent_id] = SufferingState(agent_id=agent_id)
        return self._suffering[agent_id]

    def _get_memory(self, agent_id: str) -> SemanticMemory:
        if agent_id not in self._memories:
            self._memories[agent_id] = SemanticMemory(self._hive_dir, agent_id)
        return self._memories[agent_id]

    def _load_profile(self, name: str) -> AgentProfile:
        from hive.agents.profile import default_profiles_dir

        cfg = get_config()
        profiles_dir = Path(cfg.profiles_dir) if cfg.profiles_dir else default_profiles_dir()
        try:
            return AgentProfile.from_preset(name, profiles_dir)
        except FileNotFoundError:
            return AgentProfile(name=name, role="general agent")

    async def _get_peer_summaries(self, exclude_id: str) -> list[str]:
        agents = await self._store.list_agents()
        summaries = []
        for a in agents:
            if a.agent_id == exclude_id or not a.is_alive():
                continue
            goal = await self._store.get_active_goal(a.agent_id)
            goal_text = goal["objective"][:60] if goal else "idle"
            summaries.append(f"{a.name}: {goal_text}")
        return summaries

    async def _emit(
        self, agent_id: str, session_id: str, event_type: EventType, data: dict
    ) -> None:
        event = HiveEvent(
            event_type=event_type,
            agent_id=agent_id,
            session_id=session_id,
            data=data,
        )
        await self._events.append(event)

    def stop(self) -> None:
        self._running = False
