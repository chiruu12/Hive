"""Daemon heartbeat loop — drives all agents on a cycle."""

import asyncio
import logging
from pathlib import Path
from typing import Any

from hive.agents.delegation import DelegationEngine
from hive.agents.existence import ExistenceLoop
from hive.agents.goal_strategy import GoalContext, GoalStrategy
from hive.agents.identity import IdentityManager
from hive.agents.mood import MoodRegistry
from hive.agents.profile import AgentProfile
from hive.agents.specialization import SpecializationTracker
from hive.agents.state import AgentState, AgentStatus
from hive.agents.suffering import SufferingState, assess_conditions
from hive.agents.swarm import SwarmLearning
from hive.checkpoint import CheckpointManager
from hive.config import get_config, load_config
from hive.context import ExecutionContext
from hive.daemon.hooks import HookRegistry
from hive.interactions.a2a import A2AStore
from hive.logging.models import CycleLog, GoalLog, SufferingLog
from hive.logging.writer import LogWriter
from hive.memory.events import EventLog, EventType, HiveEvent
from hive.memory.semantic import SemanticMemory
from hive.memory.store import HiveStore
from hive.models.base import BaseProvider
from hive.models.factory import create_runtime_provider
from hive.runtime import Agent, DaemonAgentAdapter, Message
from hive.runtime.persona import Persona
from hive.tools.a2a import A2AToolkit
from hive.tools.alarms import AlarmToolkit, fire_notification
from hive.tools.clipboard import ClipboardToolkit
from hive.tools.comms import CommsToolkit
from hive.tools.delegation import DaemonDelegationToolkit
from hive.tools.file import FileToolkit
from hive.tools.git import GitToolkit
from hive.tools.knowledge import KnowledgeToolkit
from hive.tools.links import LinkToolkit
from hive.tools.memory import MemoryToolkit
from hive.tools.notepad import NotepadManager, NotepadToolkit
from hive.tools.schedule import ScheduleToolkit
from hive.tools.shell import ShellToolkit
from hive.tools.sub_agents import SubAgentManager, SubAgentToolkit
from hive.tools.tasks import TaskToolkit
from hive.tools.web import WebToolkit
from hive.tools.world import WorldToolkit

logger = logging.getLogger(__name__)


class HiveDaemon:
    """Main daemon that drives all agents on a heartbeat cycle."""

    def __init__(
        self,
        hive_dir: Path,
        heartbeat: int | None = None,
        logs_dir: Path | None = None,
        profiles: list[str] | None = None,
        fresh: bool = False,
        goal_strategy: GoalStrategy | None = None,
    ):
        self._hive_dir = hive_dir
        self._goal_strategy = goal_strategy
        cfg = load_config(hive_dir)
        self._heartbeat = heartbeat or cfg.daemon.heartbeat
        self._economy_enabled = cfg.economy.enabled
        self._running = False
        self._store = HiveStore(hive_dir / "hive.db")
        self._events = EventLog(hive_dir, fsync=cfg.event_log_fsync)

        world = None
        if self._economy_enabled:
            from hive.world.state import WorldState

            world = WorldState(hive_dir)

        self._ctx = ExecutionContext(
            store=self._store,
            comms_dir=hive_dir / "comms",
            memory_dir=hive_dir / "agent_memory",
            world=world,
        )

        self._log = LogWriter(logs_dir or (hive_dir.parent / "logs"))
        self._identity = IdentityManager(hive_dir)
        self._checkpoint = CheckpointManager(hive_dir)
        self._delegation = DelegationEngine(self._store)  # a2a_store added after init
        self._specialization = SpecializationTracker()
        self._swarm = SwarmLearning(self._store, self._specialization)
        self._notepad = NotepadManager(hive_dir)
        self._sub_agents = SubAgentManager(self._store, hive_dir)
        self._a2a_store = A2AStore(hive_dir)
        self._delegation._a2a_store = self._a2a_store

        self._stats = None
        self._event_engine = None
        self._life_writer = None
        if self._economy_enabled:
            from hive.world.event_engine import EventEngine
            from hive.world.life_summary import LifeDirectoryWriter
            from hive.world.stats import StatsManager

            assert self._ctx.world is not None
            self._stats = StatsManager(hive_dir)
            self._event_engine = EventEngine(self._stats, self._ctx.world, hive_dir)
            self._life_writer = LifeDirectoryWriter(hive_dir)

        self._memories: dict[str, SemanticMemory] = {}
        self._suffering: dict[str, SufferingState] = {}
        self._personas: dict[str, Persona] = {}
        # Per-agent caches reused across cycles (B3). Provider invalidates when the
        # agent's model changes; profile when its YAML file's mtime changes.
        self._provider_cache: dict[str, tuple[str, BaseProvider]] = {}
        self._profile_cache: dict[str, tuple[float | None, AgentProfile]] = {}
        self._cycle_count = 0
        self._crisis_counts: dict[str, int] = {}
        self._profiles = profiles or []
        self._fresh = fresh
        self._hooks = HookRegistry()
        self._orch_manager: Any = None

        from hive.runtime.plugin_loader import PluginLoader

        self._plugin_loader = PluginLoader(
            [
                hive_dir / "plugins",
                hive_dir.parent / "plugins",
            ]
        )
        self._plugin_toolkits: list[type[Any]] = []

    @property
    def hooks(self) -> HookRegistry:
        return self._hooks

    def _build_toolkits(self, agent_id: str) -> list[Any]:
        workspace = self._hive_dir / "workspaces" / agent_id
        workspace.mkdir(parents=True, exist_ok=True)

        toolkits: list[Any] = [
            FileToolkit(workspace=workspace),
            ShellToolkit(workspace=workspace),
            GitToolkit(workspace=workspace),
            MemoryToolkit(path=self._ctx.memory_dir),
            CommsToolkit(path=self._ctx.comms_dir),
            DaemonDelegationToolkit(
                self._delegation,
                self._store,
            ),
            NotepadToolkit(manager=self._notepad),
            SubAgentToolkit(self._sub_agents, self._store),
            A2AToolkit(self._a2a_store, self._store),
            WebToolkit(),
            ScheduleToolkit(self._store),
            TaskToolkit(self._store),
            AlarmToolkit(self._store),
            KnowledgeToolkit(self._get_memory(agent_id)),
            LinkToolkit(self._get_memory(agent_id)),
            ClipboardToolkit(store=self._store, memory=self._get_memory(agent_id)),
        ]
        if self._economy_enabled and self._ctx.world is not None:
            toolkits.insert(0, WorldToolkit(self._ctx.world, agent_id))

        for tk in toolkits:
            tk.bind(agent_id)

        for tk_cls in self._plugin_toolkits:
            try:
                plugin_tk = tk_cls()
                plugin_tk.bind(agent_id)
                toolkits.append(plugin_tk)
            except Exception as e:
                logger.warning(
                    "Plugin toolkit %s failed: %s",
                    tk_cls.__name__,
                    e,
                )

        import shutil

        if shutil.which("claude") or shutil.which("codex"):
            from hive.orchestrator.manager import SessionManager
            from hive.orchestrator.toolkit import OrchestratorToolkit

            if self._orch_manager is None:
                self._orch_manager = SessionManager(self._hive_dir)
            orch_tk = OrchestratorToolkit(self._orch_manager)
            orch_tk.bind(agent_id)
            toolkits.append(orch_tk)

        return toolkits

    def _get_tool_names(self) -> list[str]:
        """Get tool names from runtime toolkits."""
        sample_toolkits = self._build_toolkits("__system__")
        return [t.name for tk in sample_toolkits for t in tk.get_tools()]

    def _build_tools_description(self, agent_id: str) -> str:
        """Build a text description of available tools for goal prompts."""
        toolkits = self._build_toolkits(agent_id)
        lines = []
        for tk in toolkits:
            for t in tk.get_tools():
                params = ", ".join(t.parameters.get("properties", {}).keys())
                lines.append(f"- {t.name}({params}): {t.description}")
        return "\n".join(lines)

    async def start(self, max_cycles: int | None = None) -> None:
        """Initialize store, start heartbeat.

        Args:
            max_cycles: Stop after this many cycles. ``None`` runs until stopped.
        """
        await self._store.initialize()

        if not self._fresh:
            await self._resume_agents()

        agents = await self._store.list_agents()
        agent_ids = [a.agent_id for a in agents if a.is_alive()]
        tool_names = self._get_tool_names()
        self._log.start_run(
            heartbeat=self._heartbeat,
            profiles=self._profiles,
            agents=agent_ids,
            tools=tool_names,
        )

        logger.info(
            "Daemon started: run=%s, %d tools, heartbeat=%ds, economy=%s",
            self._log.run_id,
            len(tool_names),
            self._heartbeat,
            self._economy_enabled,
        )
        self._running = True
        self._pending_shutdown = False
        self._alarm_task = asyncio.create_task(self._alarm_check_loop())
        await self._run(max_cycles)
        await self._shutdown()

    async def _alarm_check_loop(self) -> None:
        """Poll for due alarms every 15 seconds and fire notifications."""
        while self._running:
            try:
                due = await self._store.get_due_alarms()
                for alarm in due:
                    ok = await fire_notification(alarm["description"])
                    if not ok:
                        logger.warning(
                            "Alarm %s notification failed, marking fired anyway",
                            alarm["alarm_id"],
                        )
                    await self._store.mark_alarm_fired(alarm["alarm_id"])
            except Exception as e:
                logger.warning("Alarm check failed: %s", e)
            await asyncio.sleep(15)

    async def _run(self, max_cycles: int | None = None) -> None:
        goals_completed = 0
        goals_abandoned = 0
        cycles_run = 0

        new_plugins = self._plugin_loader.discover()
        self._plugin_toolkits.extend(new_plugins)
        if new_plugins:
            logger.info("Loaded %d plugin toolkits", len(new_plugins))

        while self._running:
            self._cycle_count += 1
            cycles_run += 1

            if self._cycle_count % 10 == 0:
                new = self._plugin_loader.discover()
                self._plugin_toolkits.extend(new)
                if new:
                    logger.info("Hot-loaded %d new plugin toolkits", len(new))
            agents = await self._store.list_agents()
            alive = [a for a in agents if a.is_alive()]
            crisis_count = sum(1 for a in alive if self._get_suffering(a.agent_id).in_crisis)

            cycle_timeout = get_config().daemon.cycle_timeout
            sem = asyncio.Semaphore(get_config().daemon.max_concurrent_agents)

            # Run agent cycles concurrently with bounded concurrency. Each cycle
            # is isolated (its own timeout + error handling), so one slow or
            # failing agent never blocks or breaks the others this heartbeat.
            results = await asyncio.gather(
                *(self._run_agent_cycle_guarded(agent, cycle_timeout, sem) for agent in alive)
            )
            goals_completed += sum(1 for r in results if r == "completed")
            goals_abandoned += sum(1 for r in results if r == "abandoned")

            killed = await self._sub_agents.auto_kill_expired()
            for kid in killed:
                logger.info("Auto-killed expired sub-agent: %s", kid)

            for agent in alive:
                if agent.spawned_by:
                    await self._store.increment_cycles(agent.agent_id)

            if self._economy_enabled:
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

            if max_cycles is not None and cycles_run >= max_cycles:
                break

            await asyncio.sleep(self._heartbeat)

    async def _run_agent_cycle_guarded(
        self, agent: AgentState, cycle_timeout: int, sem: asyncio.Semaphore
    ) -> str | None:
        """Run one agent's cycle under the concurrency limit, isolating failures.

        Returns the cycle result ("completed"/"abandoned"/...) or ``None`` if the
        agent timed out or errored. A timeout/exception is contained here -- it is
        logged and the agent moved to IDLE/ERROR -- so sibling agents are
        unaffected and ``asyncio.gather`` never sees an exception.
        """
        async with sem:
            try:
                if cycle_timeout > 0:
                    return await asyncio.wait_for(
                        self._run_agent_cycle(agent), timeout=cycle_timeout
                    )
                return await self._run_agent_cycle(agent)
            except TimeoutError:
                logger.warning(
                    "Cycle %d: agent %s timed out after %ds, abandoning goal",
                    self._cycle_count,
                    agent.agent_id,
                    cycle_timeout,
                )
                active_goal = await self._store.get_active_goal(agent.agent_id)
                if active_goal:
                    await self._store.abandon_goal(active_goal["goal_id"])
                await self._store.update_agent_status(agent.agent_id, AgentStatus.IDLE)
                return None
            except Exception as e:
                logger.error(
                    "Cycle %d failed for agent %s: %s",
                    self._cycle_count,
                    agent.agent_id,
                    e,
                    exc_info=True,
                )
                await self._store.update_agent_status(
                    agent.agent_id, AgentStatus.ERROR, error=str(e)
                )
                return None

    async def _run_agent_cycle(self, agent: AgentState) -> str:
        await self._hooks.emit("cycle_start", agent_id=agent.agent_id, cycle_num=self._cycle_count)

        suffering = self._get_suffering(agent.agent_id)
        result = "idle"
        try:
            result = await self._run_agent_cycle_inner(agent, suffering)
        except Exception:
            result = "error"
            raise
        finally:
            await self._hooks.emit(
                "suffering_changed",
                agent_id=agent.agent_id,
                suffering_state=suffering,
            )
            await self._hooks.emit(
                "cycle_end",
                agent_id=agent.agent_id,
                cycle_num=self._cycle_count,
                result=result,
            )
        return result

    async def _run_agent_cycle_inner(self, agent: AgentState, suffering: SufferingState) -> str:
        prev_stressors = {s.type for s in suffering.active}
        suffering.escalate_all()
        result = "idle"

        if suffering.in_crisis:
            self._crisis_counts[agent.agent_id] = self._crisis_counts.get(agent.agent_id, 0) + 1
            if self._crisis_counts[agent.agent_id] >= get_config().suffering.crisis_reset_after:
                suffering.force_reset("3+ consecutive crisis cycles")
                self._crisis_counts[agent.agent_id] = 0
        else:
            self._crisis_counts[agent.agent_id] = 0

        runtime_provider = self._get_provider(agent)
        profile = self._load_profile(agent.name)
        session_id = f"sess-{agent.agent_id}"
        identity = self._identity.load_or_create(agent.agent_id, profile)
        memory = self._get_memory(agent.agent_id)
        persona = self._get_persona(agent.agent_id, profile)

        if persona is not None:
            persona.suffering = suffering
            persona.apply_suffering_effects()

        active_goal = await self._store.get_active_goal(agent.agent_id)

        if active_goal:
            await self._store.update_agent_status(agent.agent_id, AgentStatus.WORKING)
            if persona is not None:
                runtime_agent = Agent(
                    name=agent.name,
                    model=runtime_provider,
                    persona=persona,
                    toolkits=self._build_toolkits(agent.agent_id),
                )
            else:
                runtime_agent = Agent(
                    name=agent.name,
                    model=runtime_provider,
                    system_prompt=profile.build_system_prompt(
                        economy_enabled=self._economy_enabled,
                    ),
                    toolkits=self._build_toolkits(agent.agent_id),
                )
            adapter = DaemonAgentAdapter(runtime_agent, agent.agent_id)
            # Give the pursuing agent its persistent self -- name and accumulated
            # narrative/opinions -- which the persona/profile system prompt alone
            # doesn't carry. Same context channel the suffering fragment uses.
            # A derived mood (from happiness + suffering) colours the framing.
            # Skip it in a crisis: the suffering fragment already states the
            # crisis directive, so the "overwhelmed" mood line would duplicate it.
            mood_line = ""
            if persona is not None and not suffering.in_crisis:
                mood = MoodRegistry.default().derive(
                    persona.happiness, suffering.cumulative_load, suffering.in_crisis
                )
                mood_line = mood.prompt_line()
            pursuit_context = "\n\n".join(
                p
                for p in (
                    self._identity.render_preamble(identity),
                    mood_line,
                    suffering.prompt_fragment(),
                )
                if p
            )
            outcome = await adapter.pursue_goal(
                active_goal["objective"],
                context=pursuit_context,
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
                await self._hooks.emit(
                    "goal_completed", agent_id=agent.agent_id, goal_id=active_goal["goal_id"]
                )
                if persona is not None:
                    persona.update_from_event("goal_completed", outcome.summary)
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
                # Reload so the snapshot reflects the narrative entry/chapter that
                # update_narrative just wrote (it persists its own reloaded copy).
                identity = self._identity.load(agent.agent_id) or identity
                self._checkpoint.save(
                    agent.agent_id,
                    "goal_completed",
                    suffering,
                    identity,
                    self._ctx,
                    goals_snap,
                    persona_snapshot=persona.snapshot() if persona else None,
                )
                self._specialization.record(
                    agent.agent_id,
                    "goal_pursuit",
                    True,
                    0,
                    "autonomy_loop",
                )
                if agent.spawned_by:
                    await self._store.complete_sub_agent(agent.agent_id, outcome.summary)
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
                await self._hooks.emit(
                    "goal_abandoned", agent_id=agent.agent_id, goal_id=active_goal["goal_id"]
                )
                # D1: abandonment is part of the agent's story too (success path
                # already records narrative; this closes the gap).
                self._identity.update_narrative(
                    agent.agent_id,
                    active_goal["objective"],
                    f"Abandoned: {outcome.summary}",
                )
                if persona is not None:
                    persona.update_from_event("goal_abandoned", outcome.summary)
                self._specialization.record(
                    agent.agent_id,
                    "goal_pursuit",
                    False,
                    0,
                    "autonomy_loop",
                )

            await self._check_parent_rollup(active_goal["goal_id"])
            await self._store.update_agent_status(agent.agent_id, AgentStatus.IDLE)

        else:
            due = await self._store.get_due_schedules(agent.agent_id, self._cycle_count)
            if due:
                sched = due[0]
                from uuid import uuid4

                goal_id = f"goal-{uuid4().hex[:8]}"
                await self._store.save_goal(goal_id, agent.agent_id, sched["objective"])
                await self._store.fire_schedule(sched["schedule_id"], self._cycle_count)
                logger.info(
                    "Fired scheduled goal for %s: %s",
                    agent.agent_id,
                    sched["objective"][:60],
                )
                return "idle"

            nudges = await self._store.get_pending_nudges(agent.agent_id)
            peers = await self._get_peer_summaries(agent.agent_id)

            world_status = ""
            if self._economy_enabled and self._ctx.world is not None:
                world_status = self._ctx.world.get_status(agent.agent_id)

            # D1: feed structured stats into goal generation (economy-gated).
            agent_stats = self._stats.get(agent.agent_id) if self._stats else None

            notepad_content = self._notepad.get_tail(agent.agent_id)

            pending_a2a = await self._a2a_store.get_pending_requests(agent.agent_id, limit=3)
            if pending_a2a:
                a2a_lines = []
                for m in pending_a2a:
                    a2a_lines.append(f"- [{m.type}] from {m.from_agent}: {m.subject}")
                a2a_context = "\n".join(a2a_lines)
                nudges.append(f"You have pending A2A messages:\n{a2a_context}")

            recent_goals = await self._store.list_agent_goals(agent.agent_id, limit=5)
            goal = None

            if self._goal_strategy is not None:
                ctx = GoalContext(
                    agent_id=agent.agent_id,
                    profile=profile,
                    persona=persona,
                    suffering=suffering,
                    peer_summaries=peers,
                    nudges=nudges,
                    recent_goals=recent_goals,
                    tools_description=self._build_tools_description(agent.agent_id),
                    world_status=world_status,
                    notepad_content=notepad_content,
                    economy_enabled=self._economy_enabled,
                    agent_stats=agent_stats,
                )
                result_goal = await self._goal_strategy.generate_goal(ctx)
                if result_goal is not None:
                    await self._store.save_goal(
                        result_goal.goal_id, agent.agent_id, result_goal.objective
                    )
                    goal = result_goal.objective
                    await self._hooks.emit(
                        "goal_generated",
                        agent_id=agent.agent_id,
                        goal_id=result_goal.goal_id,
                        objective=result_goal.objective,
                    )
            else:
                existence = ExistenceLoop(
                    agent_id=agent.agent_id,
                    profile=profile,
                    provider=runtime_provider,
                    store=self._store,
                    event_log=self._events,
                    hive_dir=self._hive_dir,
                    log_writer=self._log,
                    session_id=session_id,
                    economy_enabled=self._economy_enabled,
                    tools_description=self._build_tools_description(agent.agent_id),
                    world_status=world_status,
                    notepad_content=notepad_content,
                    persona=persona,
                    stats=agent_stats,
                )
                goal = await existence.generate_goal(suffering, peers, nudges)

                if goal:
                    active = await self._store.get_active_goal(agent.agent_id)
                    await self._hooks.emit(
                        "goal_generated",
                        agent_id=agent.agent_id,
                        goal_id=active["goal_id"] if active else "unknown",
                        objective=goal,
                    )

            await self._emit(
                agent.agent_id,
                session_id,
                EventType.EXISTENCE_CYCLE,
                {"goal_generated": goal or "none", "suffering_load": suffering.cumulative_load},
            )

        current_stressors = {s.type for s in suffering.active}
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
                "stressors": [s.type for s in suffering.active],
            },
        )
        return result

    def _process_payday(self, agents: list[AgentState]) -> None:
        for agent in agents:
            if self._ctx.world is None:
                continue
            job = self._ctx.world.agent_job(agent.agent_id)
            if job:
                self._ctx.world.work(agent.agent_id)

    async def _process_life_events(self, agents: list[AgentState]) -> None:
        if not self._event_engine or not self._stats:
            return
        for agent in agents:
            self._stats.tick(agent.agent_id)
            events = self._event_engine.roll_events(agent.agent_id, self._cycle_count)

            for event in events:
                prompt = self._event_engine.format_event_prompt(event)
                event_provider = create_runtime_provider(agent.model)
                profile = self._load_profile(agent.name)

                try:
                    response = await event_provider.generate(
                        messages=[
                            Message.system(
                                profile.build_system_prompt(
                                    economy_enabled=self._economy_enabled,
                                )
                            ),
                            Message.user(prompt),
                        ],
                        max_tokens=50,
                    )
                    raw = response.content.strip() if response.content else ""
                    from hive.world.event_engine import EventEngine

                    idx = EventEngine.parse_choice_index(raw, len(event.choices))
                    if idx is not None:
                        choice_id = event.choices[idx - 1].id
                    else:
                        logger.warning(
                            "Agent %s gave unparseable choice '%s' for event %s, defaulting",
                            agent.agent_id,
                            raw[:40],
                            event.name,
                        )
                        choice_id = event.choices[0].id
                except Exception as e:
                    logger.warning(
                        "LLM error for event %s agent %s: %s",
                        event.name,
                        agent.agent_id,
                        e,
                    )
                    choice_id = event.choices[0].id

                outcome = self._event_engine.apply_choice(
                    agent.agent_id,
                    event,
                    choice_id,
                    self._cycle_count,
                )

                # D1: feed the chosen outcome back into the suffering system.
                suffering = self._get_suffering(agent.agent_id)
                if outcome.stressor_added:
                    chosen = next((c for c in event.choices if c.id == outcome.choice_id), None)
                    severity = chosen.stressor_severity if chosen else None
                    suffering.add_stressor(
                        outcome.stressor_added,
                        description=f"Triggered by life event: {event.name}",
                        observable_condition="Resolved by a positive life event or recovery",
                        initial_severity=severity,
                    )
                if outcome.stressor_resolved:
                    suffering.resolve(
                        outcome.stressor_resolved,
                        note=f"Relieved by life event: {event.name}",
                    )

                # D1: record the event in the agent's narrative (not just memory).
                self._identity.update_narrative(
                    agent.agent_id,
                    f"Life event: {event.name}",
                    outcome.choice_description,
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
                        "stressor_added": outcome.stressor_added,
                        "stressor_resolved": outcome.stressor_resolved,
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

    def _get_persona(self, agent_id: str, profile: AgentProfile) -> Persona | None:
        if agent_id not in self._personas:
            if getattr(profile, "persona_config", None) is not None:
                self._personas[agent_id] = Persona.from_profile(profile)
            else:
                return None
        return self._personas.get(agent_id)

    async def _check_parent_rollup(self, goal_id: str) -> None:
        """If this goal has a parent, check if all subtasks are done."""
        goal_data = await self._store.get_goal_by_id(goal_id)
        parent_id = goal_data.get("parent_goal_id") if goal_data else None
        if not parent_id:
            return
        from hive.memory.goals import GoalEngine

        ge = GoalEngine(self._store)
        rollup = await ge.check_subtask_rollup(parent_id)
        if rollup == "completed":
            await self._store.complete_goal(parent_id)
            logger.info("Parent goal %s completed (all subtasks done)", parent_id)
        elif rollup == "abandoned":
            await self._store.abandon_goal(parent_id)
            logger.info("Parent goal %s abandoned (subtask failed)", parent_id)

    def _get_provider(self, agent: AgentState) -> BaseProvider:
        """Return a cached provider for the agent, rebuilding only if its model changed."""
        cached = self._provider_cache.get(agent.agent_id)
        if cached is None or cached[0] != agent.model:
            provider = create_runtime_provider(agent.model)
            self._provider_cache[agent.agent_id] = (agent.model, provider)
            return provider
        return cached[1]

    def _load_profile(self, name: str) -> AgentProfile:
        """Load the agent's profile, cached and invalidated on the YAML's mtime."""
        from hive.agents.profile import default_profiles_dir

        cfg = get_config()
        profiles_dir = Path(cfg.profiles_dir) if cfg.profiles_dir else default_profiles_dir()
        path = profiles_dir / f"{name}.yaml"
        mtime = path.stat().st_mtime if path.exists() else None

        cached = self._profile_cache.get(name)
        if cached is not None and cached[0] == mtime:
            return cached[1]

        try:
            profile = AgentProfile.from_preset(name, profiles_dir)
        except FileNotFoundError:
            profile = AgentProfile(name=name, role="general agent")
        self._profile_cache[name] = (mtime, profile)
        return profile

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
        self, agent_id: str, session_id: str, event_type: EventType, data: dict[str, Any]
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
        self._pending_shutdown = True

    async def _resume_agents(self) -> None:
        """Resume agents from a previous run, restoring suffering from checkpoints."""
        try:
            existing = await self._store.list_agents()
        except Exception:
            return
        resumable = [a for a in existing if a.status != AgentStatus.DEAD]
        if not resumable:
            return
        logger.info("Resuming %d agents from previous run", len(resumable))
        for agent in resumable:
            await self._store.update_agent_status(agent.agent_id, AgentStatus.IDLE)
            cps = self._checkpoint.list_checkpoints(agent.agent_id)
            if cps:
                snap = cps[0].suffering_snapshot
                try:
                    restored = SufferingState.model_validate(snap)
                    self._suffering[agent.agent_id] = restored
                    logger.info(
                        "Restored checkpoint for %s (load=%.0f%%)",
                        agent.agent_id,
                        restored.cumulative_load * 100,
                    )
                except Exception:
                    logger.warning("Could not restore suffering for %s", agent.agent_id)
                persona_snap = cps[0].persona_snapshot
                if persona_snap:
                    profile = self._load_profile(agent.name)
                    persona = self._get_persona(agent.agent_id, profile)
                    if persona is not None:
                        persona.restore_dynamic(persona_snap)
            active = await self._store.get_active_goal(agent.agent_id)
            if active:
                await self._store.abandon_goal(active["goal_id"])
                logger.info("Abandoned stale goal %s for %s", active["goal_id"], agent.agent_id)

    async def _shutdown(self) -> None:
        """Checkpoint all agents, then write life summaries if economy is on."""
        if hasattr(self, "_alarm_task") and not self._alarm_task.done():
            self._alarm_task.cancel()
            try:
                await self._alarm_task
            except asyncio.CancelledError:
                pass
        try:
            agents = await self._store.list_agents()
            for agent in agents:
                if not agent.is_alive():
                    continue
                suffering = self._get_suffering(agent.agent_id)
                identity = self._identity.load(agent.agent_id)
                persona = self._personas.get(agent.agent_id)
                goals = await self._store.list_agent_goals(agent.agent_id, limit=10)
                self._checkpoint.save(
                    agent.agent_id,
                    "daemon_shutdown",
                    suffering,
                    identity,
                    self._ctx,
                    goals,
                    persona_snapshot=persona.snapshot() if persona else None,
                )
                active = await self._store.get_active_goal(agent.agent_id)
                if active:
                    await self._store.abandon_goal(active["goal_id"])
                logger.info("Checkpointed %s on shutdown", agent.agent_id)
        except Exception as e:
            logger.warning("Checkpoint on shutdown failed: %s", e)

        if not self._economy_enabled or not self._life_writer:
            return

        try:
            agents = await self._store.list_agents()
        except Exception:
            return

        assert self._life_writer is not None
        assert self._stats is not None
        assert self._ctx.world is not None
        assert self._event_engine is not None
        for agent in agents:
            if not agent.is_alive():
                continue
            try:
                summary = self._life_writer.generate(
                    agent.agent_id,
                    self._identity,
                    self._stats,
                    self._ctx.world,
                    self._event_engine,
                    self._store,
                    self._cycle_count,
                )
                path = self._life_writer.write(summary)
                logger.info("Life summary written: %s", path)
            except Exception as e:
                logger.warning("Failed to write life summary for %s: %s", agent.agent_id, e)
