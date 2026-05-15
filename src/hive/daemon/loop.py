"""Daemon heartbeat loop — drives all agents on a cycle."""

import asyncio
import logging
from pathlib import Path
from typing import Any

from hive.agents.delegation import DelegationEngine
from hive.agents.existence import ExistenceLoop
from hive.agents.identity import IdentityManager
from hive.agents.profile import AgentProfile
from hive.agents.specialization import SpecializationTracker
from hive.agents.state import AgentState, AgentStatus
from hive.agents.suffering import SufferingState, assess_conditions
from hive.agents.swarm import SwarmLearning
from hive.checkpoint import CheckpointManager
from hive.config import get_config, load_config
from hive.context import ExecutionContext
from hive.logging.models import CycleLog, GoalLog, SufferingLog
from hive.logging.writer import LogWriter
from hive.memory.events import EventLog, EventType, HiveEvent
from hive.memory.semantic import SemanticMemory
from hive.memory.store import HiveStore
from hive.runtime import (
    Agent,
    CommsToolkit,
    DaemonAgentAdapter,
    MemoryToolkit,
    Message,
    WorldToolkit,
    create_runtime_provider,
)
from hive.runtime.dev_tools import FileToolkit, GitToolkit, ShellToolkit
from hive.runtime.toolkits import DaemonDelegationToolkit

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
    ):
        self._hive_dir = hive_dir
        cfg = load_config(hive_dir)
        self._heartbeat = heartbeat or cfg.daemon.heartbeat
        self._economy_enabled = cfg.economy.enabled
        self._running = False
        self._store = HiveStore(hive_dir / "hive.db")
        self._events = EventLog(hive_dir)

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
        self._delegation = DelegationEngine(self._store)
        self._specialization = SpecializationTracker()
        self._swarm = SwarmLearning(self._store, self._specialization)

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
        self._cycle_count = 0
        self._crisis_counts: dict[str, int] = {}
        self._profiles = profiles or []
        self._fresh = fresh

        from hive.runtime.plugin_loader import PluginLoader

        self._plugin_loader = PluginLoader(
            [
                hive_dir / "plugins",
                hive_dir.parent / "plugins",
            ]
        )
        self._plugin_toolkits: list[type[Any]] = []

    def _build_toolkits(self, agent_id: str) -> list[Any]:
        workspace = self._hive_dir / "workspaces" / agent_id
        workspace.mkdir(parents=True, exist_ok=True)

        toolkits: list[Any] = [
            FileToolkit(workspace),
            ShellToolkit(workspace),
            GitToolkit(workspace),
            MemoryToolkit(self._ctx.memory_dir, agent_id),
            CommsToolkit(self._ctx.comms_dir, agent_id),
            DaemonDelegationToolkit(
                self._delegation,
                agent_id,
                self._store,
            ),
        ]
        if self._economy_enabled and self._ctx.world is not None:
            toolkits.insert(0, WorldToolkit(self._ctx.world, agent_id))
        for tk_cls in self._plugin_toolkits:
            try:
                toolkits.append(tk_cls())
            except Exception as e:
                logger.warning(
                    "Plugin toolkit %s failed: %s",
                    tk_cls.__name__,
                    e,
                )
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

    async def start(self) -> None:
        """Initialize store, start heartbeat."""
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
        await self._run()
        await self._shutdown()

    async def _run(self) -> None:
        goals_completed = 0
        goals_abandoned = 0

        new_plugins = self._plugin_loader.discover()
        self._plugin_toolkits.extend(new_plugins)
        if new_plugins:
            logger.info("Loaded %d plugin toolkits", len(new_plugins))

        while self._running:
            self._cycle_count += 1

            if self._cycle_count % 10 == 0:
                new = self._plugin_loader.discover()
                self._plugin_toolkits.extend(new)
                if new:
                    logger.info("Hot-loaded %d new plugin toolkits", len(new))
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

        runtime_provider = create_runtime_provider(agent.model)
        profile = self._load_profile(agent.name)
        session_id = f"sess-{agent.agent_id}"
        identity = self._identity.load_or_create(agent.agent_id, profile)
        memory = self._get_memory(agent.agent_id)

        active_goal = await self._store.get_active_goal(agent.agent_id)

        if active_goal:
            await self._store.update_agent_status(agent.agent_id, AgentStatus.WORKING)
            runtime_agent = Agent(
                name=agent.name,
                model=runtime_provider,
                system_prompt=profile.build_system_prompt(
                    economy_enabled=self._economy_enabled,
                ),
                toolkits=self._build_toolkits(agent.agent_id),
            )
            adapter = DaemonAgentAdapter(runtime_agent, agent.agent_id)
            outcome = await adapter.pursue_goal(
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

            await self._check_parent_rollup(active_goal["goal_id"])
            await self._store.update_agent_status(agent.agent_id, AgentStatus.IDLE)

        else:
            nudges = await self._store.get_pending_nudges(agent.agent_id)
            peers = await self._get_peer_summaries(agent.agent_id)

            world_status = ""
            if self._economy_enabled and self._ctx.world is not None:
                world_status = self._ctx.world.get_status(agent.agent_id)

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
                    import re

                    raw = response.content.strip().lower() if response.content else ""
                    raw = re.sub(r"[^a-z0-9_]", " ", raw).strip().split()[0] if raw else ""
                    valid_ids = {c.id for c in event.choices}
                    if raw in valid_ids:
                        choice_id = raw
                    else:
                        logger.warning(
                            "Agent %s gave invalid choice '%s' for event %s, defaulting",
                            agent.agent_id,
                            raw,
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
            active = await self._store.get_active_goal(agent.agent_id)
            if active:
                await self._store.abandon_goal(active["goal_id"])
                logger.info("Abandoned stale goal %s for %s", active["goal_id"], agent.agent_id)

    async def _shutdown(self) -> None:
        """Checkpoint all agents, then write life summaries if economy is on."""
        try:
            agents = await self._store.list_agents()
            for agent in agents:
                if not agent.is_alive():
                    continue
                suffering = self._get_suffering(agent.agent_id)
                identity = self._identity.load(agent.agent_id)
                goals = await self._store.list_agent_goals(agent.agent_id, limit=10)
                self._checkpoint.save(
                    agent.agent_id, "daemon_shutdown", suffering, identity, self._ctx, goals
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
