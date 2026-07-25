"""Per-agent caches and event emission for the daemon heartbeat."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from hive.agents.profile import AgentProfile
from hive.agents.state import AgentState
from hive.agents.suffering import SufferingState
from hive.memory.events import EventType, HiveEvent
from hive.memory.semantic import SemanticMemory
from hive.models.base import BaseProvider
from hive.runtime.persona import Persona

if TYPE_CHECKING:
    from hive.daemon.loop import HiveDaemon

logger = logging.getLogger(__name__)


class AgentContextCache:
    """Per-agent caches reused across heartbeat cycles."""

    def __init__(self, daemon: HiveDaemon) -> None:
        self._d = daemon

    def get_suffering(self, agent_id: str) -> SufferingState:
        if agent_id not in self._d._suffering:
            self._d._suffering[agent_id] = SufferingState(agent_id=agent_id)
        return self._d._suffering[agent_id]

    def get_memory(self, agent_id: str) -> SemanticMemory:
        if agent_id not in self._d._memories:
            from hive.memory.migration import ensure_legacy_migrated

            mem = SemanticMemory(self._d._hive_dir, agent_id)
            ensure_legacy_migrated(
                mem,
                self._d._hive_dir,
                agent_id,
                self._d._ctx.memory_dir,
            )
            self._d._memories[agent_id] = mem
        return self._d._memories[agent_id]

    def get_persona(self, agent_id: str, profile: AgentProfile) -> Persona | None:
        if agent_id not in self._d._personas:
            if getattr(profile, "persona_config", None) is not None:
                self._d._personas[agent_id] = Persona.from_profile(profile)
            else:
                return None
        return self._d._personas.get(agent_id)

    def get_provider(self, agent: AgentState) -> BaseProvider:
        """Return a cached provider for the agent, rebuilding only if its model changed."""
        cached = self._d._provider_cache.get(agent.agent_id)
        if cached is None or cached[0] != agent.model:
            # Lazy import preserves test monkeypatches on hive.daemon.loop.create_runtime_provider
            import hive.daemon.loop as loop_module

            provider = loop_module.create_runtime_provider(agent.model)
            self._d._provider_cache[agent.agent_id] = (agent.model, provider)
            return provider
        return cached[1]

    def load_profile(self, name: str) -> AgentProfile:
        """Load the agent's profile, cached and invalidated when the YAML changes.

        The cache key is (mtime_ns, size) rather than mtime alone: coarse mtime
        granularity on some filesystems can miss a same-second edit.
        """
        from hive.agents.profile import resolve_profiles_dir

        profiles_dir = resolve_profiles_dir(self._d._hive_dir)
        path = profiles_dir / f"{name}.yaml"
        try:
            st = path.stat()
            stamp: tuple[int, int] | None = (st.st_mtime_ns, st.st_size)
        except OSError:
            stamp = None

        cached = self._d._profile_cache.get(name)
        if cached is not None and cached[0] == stamp:
            return cached[1]

        try:
            profile = AgentProfile.from_preset(name, profiles_dir)
        except FileNotFoundError:
            profile = AgentProfile(name=name, role="general agent")
        self._d._profile_cache[name] = (stamp, profile)
        return profile

    async def get_peer_summaries(self, exclude_id: str) -> list[str]:
        agents = await self._d._store.list_agents()
        summaries = []
        for a in agents:
            if a.agent_id == exclude_id or not a.is_alive():
                continue
            goal = await self._d._store.get_active_goal(a.agent_id)
            goal_text = goal["objective"][:60] if goal else "idle"
            summaries.append(f"{a.name}: {goal_text}")
        return summaries

    async def emit(
        self, agent_id: str, session_id: str, event_type: EventType, data: dict[str, Any]
    ) -> None:
        event = HiveEvent(
            event_type=event_type,
            agent_id=agent_id,
            session_id=session_id,
            data=data,
        )
        await self._d._events.append(event)
