"""Daemon heartbeat loop — drives all agents on a cycle."""

from __future__ import annotations

import asyncio
import logging
import random
from pathlib import Path
from typing import Any

from hive.agents.delegation import DelegationEngine
from hive.agents.goal_strategy import GoalStrategy
from hive.agents.identity import IdentityManager
from hive.agents.profile import AgentProfile
from hive.agents.specialization import SpecializationTracker
from hive.agents.state import AgentState
from hive.agents.suffering import SufferingState
from hive.agents.swarm import SwarmLearning
from hive.agents.swarm_policy import PassiveSwarmPolicy, SwarmPolicy
from hive.checkpoint import CheckpointManager
from hive.config import get_config, load_config
from hive.context import ExecutionContext
from hive.daemon.agent_context import AgentContextCache
from hive.daemon.agent_cycle import AgentCycleRunner
from hive.daemon.budget import BudgetTracker
from hive.daemon.economy_hooks import EconomyHooks
from hive.daemon.heartbeat import HeartbeatLoop
from hive.daemon.hooks import HookRegistry
from hive.daemon.phase import CyclePhase
from hive.daemon.run_lifecycle import RunLifecycle
from hive.daemon.toolkit_factory import ToolkitFactory
from hive.daemon.wakeup import A2AWakeSource, FileWakeSource, NudgeWakeSource, WakeSource
from hive.interactions.a2a import A2AStore
from hive.logging.writer import LogWriter
from hive.memory.events import EventLog, EventType
from hive.memory.semantic import SemanticMemory
from hive.memory.store import HiveStore
from hive.models.base import BaseProvider
from hive.models.factory import create_runtime_provider
from hive.runtime.guardrails import build_guardrail_pipeline
from hive.runtime.persona import Persona
from hive.tools.notepad import NotepadManager
from hive.tools.sub_agents import SubAgentManager

logger = logging.getLogger(__name__)

# Re-export for tests that monkeypatch hive.daemon.loop.create_runtime_provider
__all__ = ["HiveDaemon", "create_runtime_provider"]


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
        swarm_policy: SwarmPolicy | None = None,
    ):
        self._hive_dir = hive_dir
        self._goal_strategy = goal_strategy
        from hive.config import resolve_logs_dir

        cfg = load_config(hive_dir)
        self._heartbeat = heartbeat or cfg.daemon.heartbeat
        self._economy_enabled = cfg.economy.enabled
        self._guardrails = build_guardrail_pipeline(cfg.guardrails)
        self._running = False
        # Set by stop() to break the heartbeat sleep immediately instead of
        # waiting up to a full heartbeat. Created in start() (needs a running loop).
        self._stop_event: asyncio.Event | None = None
        self._alarm_task: asyncio.Task[None] | None = None
        self._store = HiveStore(hive_dir / "hive.db")
        self._events = EventLog(hive_dir, fsync=cfg.event_log_fsync)

        # Deterministic mode: when cfg.seed is set, the stochastic world layer
        # (life events, luck, gambling) draws from reproducible streams. Each
        # subsystem gets its own derived stream so one's draws don't perturb the
        # other. seed=None keeps system-entropy behavior. Recorded in manifest.
        self._seed = cfg.seed
        self._event_rng = random.Random(cfg.seed)
        self._world_rng = random.Random(None if cfg.seed is None else cfg.seed + 1)

        world = None
        if self._economy_enabled:
            from hive.world.state import WorldState

            world = WorldState(hive_dir, rng=self._world_rng)

        self._ctx = ExecutionContext(
            store=self._store,
            comms_dir=hive_dir / "comms",
            memory_dir=hive_dir / "agent_memory",
            world=world,
        )

        self._log = LogWriter(resolve_logs_dir(hive_dir, logs_dir))
        self._identity = IdentityManager(hive_dir)
        self._checkpoint = CheckpointManager(hive_dir)
        self._delegation = DelegationEngine(self._store)  # a2a_store added after init
        self._specialization = SpecializationTracker()
        self._swarm = SwarmLearning(self._store, self._specialization)
        self._swarm_policy: SwarmPolicy = swarm_policy or PassiveSwarmPolicy()
        self._notepad = NotepadManager(hive_dir)
        self._sub_agents = SubAgentManager(self._store, hive_dir)
        self._a2a_store = A2AStore(hive_dir)
        self._delegation._a2a_store = self._a2a_store

        # Wake sources — allow external events to interrupt the heartbeat sleep.
        # A2A messages land under <hive>/a2a/<agent_id>/inbox.jsonl.
        # Nudge wake files land under <hive>/nudges/ (see touch_nudge_wake_file).
        wake_poll = cfg.daemon.wake_poll_interval
        self._wake_sources: list[WakeSource] = [
            A2AWakeSource(hive_dir / "a2a", poll_interval=wake_poll),
            NudgeWakeSource(hive_dir / "nudges", poll_interval=wake_poll),
        ]
        for watch_path in cfg.daemon.watch_files:
            self._wake_sources.append(
                FileWakeSource(Path(watch_path).expanduser(), poll_interval=wake_poll)
            )

        self._stats = None
        self._event_engine = None
        self._life_writer = None
        if self._economy_enabled:
            from hive.world.event_engine import EventEngine
            from hive.world.life_summary import LifeDirectoryWriter
            from hive.world.stats import StatsManager

            assert self._ctx.world is not None
            self._stats = StatsManager(hive_dir)
            self._event_engine = EventEngine(
                self._stats, self._ctx.world, hive_dir, rng=self._event_rng
            )
            self._life_writer = LifeDirectoryWriter(hive_dir)

        # Per-agent state caches. Accessed only from the daemon's event loop via
        # synchronous get-or-create accessors with no awaits inside, so concurrent
        # agent cycles cannot interleave mid-access -- no locks needed. Keep the
        # accessors await-free to preserve this invariant.
        self._memories: dict[str, SemanticMemory] = {}
        self._suffering: dict[str, SufferingState] = {}
        self._personas: dict[str, Persona] = {}
        # Per-agent caches reused across cycles (B3). Provider invalidates when the
        # agent's model changes; profile when its YAML file changes on disk.
        self._provider_cache: dict[str, tuple[str, BaseProvider]] = {}
        self._profile_cache: dict[str, tuple[tuple[int, int] | None, AgentProfile]] = {}
        self._cycle_count = 0
        self._crisis_counts: dict[str, int] = {}
        self._profiles = profiles or []
        self._fresh = fresh
        self._hooks = HookRegistry()

        from hive.runtime.plugin_loader import PluginLoader

        plugins_cfg = get_config().plugins
        self._plugin_loader = PluginLoader(
            [
                hive_dir / "plugins",
                hive_dir.parent / "plugins",
            ],
            allowlist=plugins_cfg.allowlist or None,
            enabled=plugins_cfg.enabled,
        )
        self._plugin_toolkits: list[type[Any]] = []

        # Toolkit factory — centralises all toolkit construction
        self._toolkit_factory = ToolkitFactory(
            hive_dir=hive_dir,
            ctx=self._ctx,
            store=self._store,
            delegation=self._delegation,
            notepad=self._notepad,
            sub_agents=self._sub_agents,
            a2a_store=self._a2a_store,
            economy_enabled=self._economy_enabled,
            plugin_toolkits=self._plugin_toolkits,
            get_memory=self._get_memory,
            guardrails=self._guardrails,
        )

        # Budget tracker — daemon-level cost kill switch
        budget_cfg = cfg.daemon
        self._budget_exceeded = False

        def _on_budget_exceeded(summary: Any) -> None:
            if not self._budget_exceeded:
                self._budget_exceeded = True
                logger.error(
                    "Daemon budget exceeded — halting new LLM work "
                    "(spent $%.4f / $%.4f, %d / %d tokens)",
                    summary.spent_usd,
                    summary.budget_usd,
                    summary.spent_tokens,
                    summary.budget_tokens,
                )

        self._budget = BudgetTracker(
            budget_usd=budget_cfg.budget_usd,
            budget_tokens=budget_cfg.budget_tokens,
            on_exceeded=_on_budget_exceeded,
            mode=budget_cfg.budget_mode,
        )
        self._budget_persist = budget_cfg.budget_persist
        self._budget_ledger_path = hive_dir / "budget.json"
        if self._budget_persist:
            self._budget.load_from(self._budget_ledger_path)
            if self._budget.is_exceeded():
                self._budget_exceeded = True

        # Register the budget kill-switch on every phase that spends tokens:
        # goal pursuit AND goal generation both make LLM calls, so guarding only
        # one lets the other keep spending past the cap.
        from hive.daemon.gates import CostBudgetGuard, ManualPauseGuard

        budget_guard = CostBudgetGuard(self._budget)
        guard_fail_closed = budget_cfg.guards_fail_closed
        self._pause_guard = ManualPauseGuard()
        self._pause_file = hive_dir / "daemon.paused"
        if self._pause_file.exists():
            self._pause_guard.paused = True

        for phase in CyclePhase:
            self._hooks.register_guard(phase, self._pause_guard, fail_closed=guard_fail_closed)
        self._hooks.register_guard(
            CyclePhase.GOAL_PURSUIT, budget_guard, fail_closed=guard_fail_closed
        )
        self._hooks.register_guard(
            CyclePhase.GOAL_GENERATION, budget_guard, fail_closed=guard_fail_closed
        )

        self._agent_context = AgentContextCache(self)
        self._cycle_runner = AgentCycleRunner(self, self._agent_context)
        self._economy_hooks = EconomyHooks(self, self._agent_context)
        self._heartbeat_loop = HeartbeatLoop(
            self, self._cycle_runner, self._economy_hooks, self._agent_context
        )
        self._run_lifecycle = RunLifecycle(self, self._agent_context)

    @property
    def hooks(self) -> HookRegistry:
        return self._hooks

    @property
    def budget(self) -> BudgetTracker:
        return self._budget

    @property
    def budget_exceeded(self) -> bool:
        """True after the daemon budget kill-switch has fired."""
        return self._budget_exceeded

    async def reset_budget(self) -> None:
        """Clear spent totals (and persisted ledger when enabled)."""
        await self._budget.reset()
        self._budget_exceeded = False
        if self._budget_persist:
            self._budget.save_to(self._budget_ledger_path)

    def persist_budget(self) -> None:
        """Write spent totals to disk when persistence is enabled."""
        if self._budget_persist:
            self._budget.save_to(self._budget_ledger_path)

    @property
    def paused(self) -> bool:
        """True when the daemon-wide ManualPauseGuard is active."""
        return self._pause_guard.paused

    def pause(self) -> None:
        """Freeze all agent cycles via ManualPauseGuard (daemon-wide, not per-agent)."""
        self._pause_guard.paused = True
        self._pause_file.write_text("1\n")

    def resume(self) -> None:
        """Clear the daemon-wide pause."""
        self._pause_guard.paused = False
        self._pause_file.unlink(missing_ok=True)

    def sync_pause_from_file(self) -> None:
        """Sync in-memory pause state from ``.hive/daemon.paused`` (CLI/file IPC)."""
        self._pause_guard.paused = self._pause_file.exists()

    def reload_config(self) -> None:
        """Apply hot-reloadable settings from disk into the running daemon."""
        from hive.config import reload_config_from_disk

        cfg = reload_config_from_disk(self._hive_dir)
        self._heartbeat = cfg.daemon.heartbeat

        poll = cfg.daemon.wake_poll_interval
        for src in self._wake_sources:
            if hasattr(src, "_poll"):
                src._poll = poll

        self._events._fsync = cfg.event_log_fsync

        if not cfg.daemon.toolkit_cache:
            self._toolkit_factory.invalidate_agent_cache()

    def add_wake_source(self, source: WakeSource) -> None:
        """Register an extra wake source raced against the heartbeat sleep."""
        self._wake_sources.append(source)

    def _build_toolkits(self, agent_id: str, *, is_sub_agent: bool = False) -> list[Any]:
        return self._toolkit_factory.build(agent_id, is_sub_agent=is_sub_agent)

    def _get_tool_names(self) -> list[str]:
        return self._toolkit_factory.tool_names()

    def _build_tools_description(self, agent_id: str, *, is_sub_agent: bool = False) -> str:
        return self._toolkit_factory.tools_description(agent_id, is_sub_agent=is_sub_agent)

    async def start(self, max_cycles: int | None = None) -> None:
        await self._run_lifecycle.start(max_cycles)

    async def _alarm_check_loop(self) -> None:
        await self._run_lifecycle.alarm_check_loop()

    async def _run(self, max_cycles: int | None = None) -> None:
        await self._heartbeat_loop.run(max_cycles)

    async def _run_agent_cycle_guarded(
        self, agent: AgentState, cycle_timeout: int, sem: Any
    ) -> str | None:
        return await self._cycle_runner.run_guarded(agent, cycle_timeout, sem)

    async def _run_agent_cycle(self, agent: AgentState) -> str:
        return await self._cycle_runner.run(agent)

    def _process_payday(self, agents: list[AgentState]) -> None:
        self._economy_hooks.process_payday(agents)

    async def _process_life_events(self, agents: list[AgentState]) -> None:
        await self._economy_hooks.process_life_events(agents)

    def _get_suffering(self, agent_id: str) -> SufferingState:
        return self._agent_context.get_suffering(agent_id)

    def _get_memory(self, agent_id: str) -> SemanticMemory:
        return self._agent_context.get_memory(agent_id)

    def _get_persona(self, agent_id: str, profile: AgentProfile) -> Persona | None:
        return self._agent_context.get_persona(agent_id, profile)

    def _get_provider(self, agent: AgentState) -> BaseProvider:
        return self._agent_context.get_provider(agent)

    def _load_profile(self, name: str) -> AgentProfile:
        return self._agent_context.load_profile(name)

    async def _get_peer_summaries(self, exclude_id: str) -> list[str]:
        return await self._agent_context.get_peer_summaries(exclude_id)

    async def _emit(
        self, agent_id: str, session_id: str, event_type: EventType, data: dict[str, Any]
    ) -> None:
        await self._agent_context.emit(agent_id, session_id, event_type, data)

    def stop(self) -> None:
        self._running = False
        if self._stop_event is not None:
            self._stop_event.set()

    async def _resume_agents(self) -> None:
        await self._run_lifecycle.resume_agents()

    async def _shutdown(self) -> None:
        await self._run_lifecycle.shutdown()
