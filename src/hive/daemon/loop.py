"""Daemon heartbeat loop — drives all agents on a cycle."""

import asyncio
import logging
from pathlib import Path

from hive.agents.existence import ExistenceLoop
from hive.agents.loop import AgentLoop
from hive.agents.profile import AgentProfile
from hive.agents.state import AgentState, AgentStatus
from hive.agents.suffering import SufferingState, assess_conditions
from hive.execution.registry import ToolRegistry
from hive.execution.tools.comms import set_comms_dir
from hive.execution.tools.memory_tools import set_memory_dir
from hive.memory.events import EventLog, EventType, HiveEvent
from hive.memory.store import HiveStore
from hive.models.router import create_provider

logger = logging.getLogger(__name__)

DEFAULT_HEARTBEAT = 10


class HiveDaemon:
    """Main daemon that drives all agents on a heartbeat cycle."""

    def __init__(
        self,
        hive_dir: Path,
        heartbeat: int = DEFAULT_HEARTBEAT,
    ):
        self._hive_dir = hive_dir
        self._heartbeat = heartbeat
        self._running = False
        self._store = HiveStore(hive_dir / "hive.db")
        self._events = EventLog(hive_dir)
        self._registry = ToolRegistry()
        self._suffering: dict[str, SufferingState] = {}
        self._cycle_count = 0
        self._crisis_counts: dict[str, int] = {}

    async def start(self) -> None:
        """Initialize subsystems and start the heartbeat."""
        await self._store.initialize()
        set_memory_dir(self._hive_dir)
        set_comms_dir(self._hive_dir)
        self._registry.discover()
        logger.info(
            "Daemon started: %d tools registered, heartbeat=%ds",
            len(self._registry.list_tools()),
            self._heartbeat,
        )
        self._running = True
        await self._run()

    async def _run(self) -> None:
        while self._running:
            self._cycle_count += 1
            agents = await self._store.list_agents()
            alive = [a for a in agents if a.is_alive()]

            for agent in alive:
                try:
                    await self._run_agent_cycle(agent)
                except Exception as e:
                    logger.error("Cycle failed for %s: %s", agent.agent_id, e)
                    await self._store.update_agent_status(
                        agent.agent_id, AgentStatus.ERROR, error=str(e)
                    )

            await asyncio.sleep(self._heartbeat)

    async def _run_agent_cycle(self, agent: AgentState) -> None:
        suffering = self._get_suffering(agent.agent_id)
        suffering.escalate_all()

        if suffering.in_crisis:
            self._crisis_counts[agent.agent_id] = self._crisis_counts.get(agent.agent_id, 0) + 1
            if self._crisis_counts[agent.agent_id] >= 3:
                suffering.force_reset("3+ consecutive crisis cycles")
                self._crisis_counts[agent.agent_id] = 0
        else:
            self._crisis_counts[agent.agent_id] = 0

        provider = create_provider(agent.model)
        profile = self._load_profile(agent.name)
        session_id = f"sess-{agent.agent_id}"

        active_goal = await self._store.get_active_goal(agent.agent_id)

        if active_goal:
            await self._store.update_agent_status(agent.agent_id, AgentStatus.WORKING)
            loop = AgentLoop(
                agent_id=agent.agent_id,
                profile=profile,
                provider=provider,
                registry=self._registry,
                store=self._store,
                event_log=self._events,
                session_id=session_id,
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
                await self._emit(
                    agent.agent_id,
                    session_id,
                    EventType.GOAL_COMPLETED,
                    {
                        "goal_id": active_goal["goal_id"],
                        "summary": outcome.summary,
                    },
                )
            elif outcome.steps_failed > outcome.steps_done:
                await self._store.abandon_goal(active_goal["goal_id"])
                await self._emit(
                    agent.agent_id,
                    session_id,
                    EventType.GOAL_ABANDONED,
                    {
                        "goal_id": active_goal["goal_id"],
                        "reason": outcome.summary,
                    },
                )

            await self._store.update_agent_status(agent.agent_id, AgentStatus.IDLE)

        else:
            nudges = await self._store.get_pending_nudges(agent.agent_id)
            peers = await self._get_peer_summaries(agent.agent_id)

            existence = ExistenceLoop(
                agent_id=agent.agent_id,
                profile=profile,
                provider=provider,
                registry=self._registry,
                store=self._store,
                event_log=self._events,
                session_id=session_id,
            )
            goal = await existence.generate_goal(suffering, peers, nudges)

            await self._emit(
                agent.agent_id,
                session_id,
                EventType.EXISTENCE_CYCLE,
                {
                    "goal_generated": goal or "none",
                    "suffering_load": suffering.cumulative_load,
                },
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

    def _get_suffering(self, agent_id: str) -> SufferingState:
        if agent_id not in self._suffering:
            self._suffering[agent_id] = SufferingState(agent_id=agent_id)
        return self._suffering[agent_id]

    def _load_profile(self, name: str) -> AgentProfile:
        profiles_dir = self._hive_dir.parent / "profiles"
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
