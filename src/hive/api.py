"""Programmatic Python API — use Hive as a library."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from hive.agents.profile import AgentProfile, default_profiles_dir
from hive.agents.state import AgentState, AgentStatus
from hive.daemon.loop import HiveDaemon
from hive.daemon.setup import initialize_hive
from hive.memory.store import HiveStore

logger = logging.getLogger(__name__)


def _run_sync(coro: Any) -> Any:
    """Run an async coroutine synchronously."""
    try:
        asyncio.get_running_loop()
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    except RuntimeError:
        return asyncio.run(coro)


class Hive:
    """Facade for the Hive agent framework.

    Usage::

        hive = Hive()
        hive.init()
        hive.spawn("coder")
        hive.start(cycles=5)
        print(hive.status())
    """

    def __init__(self, path: Path | None = None):
        self._root = path or Path.cwd()
        self._hive_dir = self._root / ".hive"
        self._store: HiveStore | None = None
        self._daemon: HiveDaemon | None = None

    def _get_store(self) -> HiveStore:
        if self._store is None:
            self._store = HiveStore(self._hive_dir / "hive.db")
            _run_sync(self._store.initialize())
        return self._store

    def init(self) -> None:
        """Initialize a new hive directory structure."""
        initialize_hive(self._root)

    def spawn(
        self,
        preset: str,
        model: str | None = None,
    ) -> str:
        """Spawn an agent from a preset profile. Returns agent_id."""
        profiles_dir = default_profiles_dir()
        profile = AgentProfile.from_preset(preset, profiles_dir)
        if model:
            profile.model = model

        agent_id = f"{profile.name}-{uuid4().hex[:8]}"
        state = AgentState(
            agent_id=agent_id,
            name=profile.name,
            role=profile.role,
            model=profile.model,
            status=AgentStatus.IDLE,
            workspace=str(self._hive_dir / "workspaces" / agent_id),
        )
        store = self._get_store()
        _run_sync(store.save_agent(state))
        return agent_id

    def start(
        self,
        cycles: int | None = None,
        heartbeat: int = 10,
        profiles: list[str] | None = None,
        fresh: bool = False,
    ) -> None:
        """Start the daemon. Blocks until stopped or cycles exhausted.

        Args:
            cycles: Run this many cycles then stop. None = run forever.
            heartbeat: Seconds between cycles.
            profiles: Profile names to auto-spawn if no agents exist.
            fresh: Ignore saved state from previous runs.
        """
        self._daemon = HiveDaemon(
            self._hive_dir,
            heartbeat=heartbeat,
            logs_dir=self._root / "logs",
            profiles=profiles or [],
            fresh=fresh,
        )

        if cycles is not None:
            daemon = self._daemon

            async def _bounded_run() -> None:
                daemon._plugin_toolkits.extend(daemon._plugin_loader.discover())
                count = 0
                while daemon._running and count < cycles:
                    daemon._cycle_count += 1
                    count += 1
                    agents = await daemon._store.list_agents()
                    alive = [a for a in agents if a.is_alive()]
                    for a in alive:
                        try:
                            await daemon._run_agent_cycle(a)
                        except Exception as e:
                            logger.error(
                                "Cycle failed for %s: %s",
                                a.agent_id,
                                e,
                            )
                    if count < cycles:
                        await asyncio.sleep(daemon._heartbeat)
                daemon._running = False

            daemon._run = _bounded_run  # type: ignore[method-assign]

        asyncio.run(self._daemon.start())

    def stop(self) -> None:
        """Signal the daemon to stop."""
        if self._daemon:
            self._daemon.stop()

    def status(self) -> list[dict[str, Any]]:
        """Return status of all agents."""
        store = self._get_store()
        agents = _run_sync(store.list_agents())
        result = []
        for a in agents:
            goal = _run_sync(store.get_active_goal(a.agent_id))
            result.append(
                {
                    "agent_id": a.agent_id,
                    "name": a.name,
                    "role": a.role,
                    "model": a.model,
                    "status": a.status.value,
                    "goal": goal["objective"] if goal else None,
                }
            )
        return result

    def nudge(self, agent: str, message: str) -> None:
        """Send a nudge message to an agent."""
        store = self._get_store()
        agent_id = self._resolve_agent(agent)
        nudge_id = f"nudge-{uuid4().hex[:8]}"
        _run_sync(store.save_nudge(nudge_id, agent_id, message))

    def inspect(self, run_id: str) -> dict[str, Any] | None:
        """Get summary of a recorded run."""
        from hive.logging.reader import LogReader

        reader = LogReader(self._root / "logs")
        return reader.get_summary(run_id)

    def kill(self, agent: str) -> None:
        """Terminate an agent."""
        store = self._get_store()
        agent_id = self._resolve_agent(agent)
        _run_sync(store.update_agent_status(agent_id, AgentStatus.DEAD))

    def _resolve_agent(self, name_or_id: str) -> str:
        """Resolve an agent name, ID, or prefix to a full agent_id."""
        store = self._get_store()
        agents: list[AgentState] = _run_sync(store.list_agents())
        for a in agents:
            if a.agent_id == name_or_id:
                return a.agent_id
        for a in agents:
            if a.name == name_or_id:
                return a.agent_id
        for a in agents:
            if a.agent_id.startswith(name_or_id):
                return a.agent_id
        raise ValueError(f"Agent not found: {name_or_id}")
