"""Characterization tests for AgentCycleRunner phase order and hook semantics.

These tests capture golden behavior before/after agent_cycle module decomposition.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from hive.agents.state import AgentState, AgentStatus
from hive.config import HiveConfig, set_config
from hive.daemon.agent_cycle import AgentCycleRunner
from hive.daemon.phase import CyclePhase
from hive.memory.store import HiveStore
from hive.models.base import BaseProvider
from hive.runtime.types import GenerateResult, Message


class _NoGoalProvider(BaseProvider):
    """Returns no goal so the cycle runs generation then cleanup."""

    def __init__(self) -> None:
        super().__init__("mock-model")

    @property
    def available(self) -> bool:
        return True

    async def generate_with_metadata(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> GenerateResult:
        content = json.dumps({"goal": None, "reasoning": "nothing to do"})
        return GenerateResult(
            message=Message.assistant(content),
            model="mock-model",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.0001,
            duration_ms=50,
        )

    async def generate_structured(
        self,
        messages: list[Message],
        output_type: type[Any],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Any:
        raise NotImplementedError


def _mock_provider(_model: str) -> _NoGoalProvider:
    return _NoGoalProvider()


@pytest.fixture
def hive_dir(tmp_path: Path) -> Path:
    hive = tmp_path / ".hive"
    hive.mkdir()
    for sub in ("sessions", "workspaces", "comms", "agent_memory", "checkpoints"):
        (hive / sub).mkdir()
    cfg = HiveConfig()
    cfg.economy.enabled = False
    set_config(cfg)
    cfg.save(hive)
    return hive


async def _seed_agent(store: HiveStore) -> AgentState:
    state = AgentState(
        agent_id="char-test0001",
        name="researcher",
        role="research assistant",
        model="mock-model",
        status=AgentStatus.IDLE,
        workspace=".",
    )
    await store.save_agent(state)
    return state


class TestAgentCyclePhaseOrder:
    @pytest.mark.asyncio
    async def test_idle_agent_runs_phases_in_order(self, hive_dir: Path) -> None:
        """Full cycle without active goal: six phases, generation not pursuit."""
        from hive.daemon.loop import HiveDaemon

        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        agent = await _seed_agent(store)

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")
        phase_log: list[str] = []

        async def on_phase_enter(**kwargs: object) -> None:
            phase = kwargs.get("phase")
            if isinstance(phase, CyclePhase):
                phase_log.append(f"enter:{phase.value}")

        async def on_phase_exit(**kwargs: object) -> None:
            phase = kwargs.get("phase")
            if isinstance(phase, CyclePhase):
                phase_log.append(f"exit:{phase.value}")

        daemon.hooks.on("phase_enter", on_phase_enter)
        daemon.hooks.on("phase_exit", on_phase_exit)

        with patch(
            "hive.daemon.loop.create_runtime_provider",
            side_effect=_mock_provider,
        ):
            result = await daemon._run_agent_cycle(agent)

        assert result == "idle"
        enters = [e for e in phase_log if e.startswith("enter:")]
        assert enters == [
            "enter:approval_gate",
            "enter:suffering_escalation",
            "enter:context_assembly",
            "enter:goal_generation",
            "enter:cleanup",
        ]
        assert "enter:goal_pursuit" not in enters

    @pytest.mark.asyncio
    async def test_guard_block_emits_no_later_phases(self, hive_dir: Path) -> None:
        from hive.daemon.loop import HiveDaemon

        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        agent = await _seed_agent(store)

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")
        daemon.pause()

        phase_log: list[str] = []

        async def on_phase_enter(**kwargs: object) -> None:
            phase = kwargs.get("phase")
            if isinstance(phase, CyclePhase):
                phase_log.append(phase.value)

        daemon.hooks.on("phase_enter", on_phase_enter)

        with patch(
            "hive.daemon.loop.create_runtime_provider",
            side_effect=_mock_provider,
        ):
            result = await daemon._run_agent_cycle(agent)

        assert result == "guarded"
        # Guards veto before phase_enter is emitted.
        assert phase_log == []

    @pytest.mark.asyncio
    async def test_cycle_hooks_fire_start_and_end(self, hive_dir: Path) -> None:
        from hive.daemon.loop import HiveDaemon

        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        agent = await _seed_agent(store)

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")
        events: list[str] = []

        async def on_start(**kwargs: object) -> None:
            events.append("cycle_start")

        async def on_end(**kwargs: object) -> None:
            events.append("cycle_end")

        daemon.hooks.on("cycle_start", on_start)
        daemon.hooks.on("cycle_end", on_end)

        with patch(
            "hive.daemon.loop.create_runtime_provider",
            side_effect=_mock_provider,
        ):
            await daemon._run_agent_cycle(agent)

        assert events == ["cycle_start", "cycle_end"]


class TestAgentCycleTimeoutBranch:
    @pytest.mark.asyncio
    async def test_run_guarded_timeout_abandons_goal(self, hive_dir: Path) -> None:
        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        agent = await _seed_agent(store)
        await store.save_goal("goal-timeout", agent.agent_id, "Slow task")

        cfg = HiveConfig.load(hive_dir)
        cfg.daemon.cycle_timeout = 1
        cfg.daemon.preserve_active_goals_on_timeout = False
        set_config(cfg)
        cfg.save(hive_dir)

        from hive.daemon.loop import HiveDaemon

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")

        async def _hanging_cycle(_agent: AgentState) -> str:
            await asyncio.sleep(10)
            return "completed"

        daemon._run_agent_cycle = _hanging_cycle  # type: ignore[method-assign]

        sem = asyncio.Semaphore(8)
        result = await AgentCycleRunner(daemon, daemon._agent_context).run_guarded(
            agent, cycle_timeout=1, sem=sem
        )

        assert result is None
        updated = await store.get_agent(agent.agent_id)
        assert updated is not None
        assert updated.status == AgentStatus.IDLE
        assert await store.get_active_goal(agent.agent_id) is None

    @pytest.mark.asyncio
    async def test_run_guarded_timeout_preserves_goal_when_configured(self, hive_dir: Path) -> None:
        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        agent = await _seed_agent(store)
        await store.save_goal("goal-preserve", agent.agent_id, "Slow task")

        cfg = HiveConfig.load(hive_dir)
        cfg.daemon.cycle_timeout = 1
        cfg.daemon.preserve_active_goals_on_timeout = True
        set_config(cfg)
        cfg.save(hive_dir)

        from hive.daemon.loop import HiveDaemon

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")

        async def _hanging_cycle(_agent: AgentState) -> str:
            await asyncio.sleep(10)
            return "completed"

        daemon._run_agent_cycle = _hanging_cycle  # type: ignore[method-assign]

        sem = asyncio.Semaphore(8)
        result = await AgentCycleRunner(daemon, daemon._agent_context).run_guarded(
            agent, cycle_timeout=1, sem=sem
        )

        assert result is None
        active = await store.get_active_goal(agent.agent_id)
        assert active is not None
        assert active["goal_id"] == "goal-preserve"
