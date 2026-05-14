"""Tests for auto-resume — checkpoint on shutdown, restore on restart."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from hive.agents.state import AgentState, AgentStatus
from hive.agents.suffering import StressorType, SufferingState
from hive.checkpoint import CheckpointManager
from hive.config import HiveConfig, set_config
from hive.context import ExecutionContext
from hive.daemon.loop import HiveDaemon
from hive.memory.store import HiveStore
from hive.runtime.types import GenerateResult, Message, ToolCall


class MockResumeProvider:
    def __init__(self) -> None:
        self._call_count = 0

    @property
    def available(self) -> bool:
        return True

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Message:
        result = await self.generate_with_metadata(messages, tools, temperature, max_tokens)
        return result.message

    async def generate_with_metadata(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> GenerateResult:
        self._call_count += 1
        prompt = " ".join(m.content for m in messages).lower()

        if "what is the single most valuable" in prompt or "your task" in prompt:
            content = json.dumps({
                "goal": "Learn testing patterns",
                "reasoning": "Improve code quality",
            })
            msg = Message.assistant(content)
        elif tools:
            msg = Message.assistant(
                "Storing results.",
                [ToolCall(id=f"tc-{self._call_count}", name="memory_set",
                          arguments={"key": "data", "value": "test"})],
            )
        else:
            msg = Message.assistant("Done.")

        return GenerateResult(
            message=msg, model="mock", input_tokens=10,
            output_tokens=5, cost_usd=0.0, duration_ms=10,
        )


def _mock_provider(model_name: str) -> MockResumeProvider:
    return MockResumeProvider()


@pytest.fixture
def hive_dir(tmp_path: Path) -> Path:
    hive = tmp_path / ".hive"
    hive.mkdir()
    for d in ["sessions", "workspaces", "comms", "agent_memory", "checkpoints"]:
        (hive / d).mkdir()
    cfg = HiveConfig()
    cfg.economy.enabled = False
    set_config(cfg)
    cfg.save(hive)
    return hive


async def _seed_agent(store: HiveStore, agent_id: str = "coder-test01") -> AgentState:
    state = AgentState(
        agent_id=agent_id, name="coder", role="developer",
        model="mock", status=AgentStatus.IDLE, workspace=".",
    )
    await store.save_agent(state)
    return state


class TestShutdownCheckpoint:
    @pytest.mark.asyncio
    async def test_shutdown_creates_checkpoints(self, hive_dir: Path) -> None:
        """Shutdown saves a checkpoint for each alive agent."""
        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        await _seed_agent(store, "agent-a")
        await _seed_agent(store, "agent-b")

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")

        daemon._store = store
        daemon._running = False

        with patch("hive.daemon.loop.create_runtime_provider", side_effect=_mock_provider):
            await daemon._shutdown()

        cp_mgr = CheckpointManager(hive_dir)
        cps_a = cp_mgr.list_checkpoints("agent-a")
        cps_b = cp_mgr.list_checkpoints("agent-b")
        assert len(cps_a) >= 1
        assert len(cps_b) >= 1
        assert cps_a[0].label == "daemon_shutdown"

    @pytest.mark.asyncio
    async def test_shutdown_abandons_active_goals(self, hive_dir: Path) -> None:
        """Active goals are marked abandoned on shutdown."""
        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        await _seed_agent(store, "agent-c")
        await store.save_goal("goal-1", "agent-c", "In-progress work")

        active = await store.get_active_goal("agent-c")
        assert active is not None

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")
        daemon._store = store
        daemon._running = False

        with patch("hive.daemon.loop.create_runtime_provider", side_effect=_mock_provider):
            await daemon._shutdown()

        active_after = await store.get_active_goal("agent-c")
        assert active_after is None

        goals = await store.list_agent_goals("agent-c")
        assert goals[0]["status"] == "abandoned"


class TestResumeOnStart:
    @pytest.mark.asyncio
    async def test_resume_restores_agents(self, hive_dir: Path) -> None:
        """Daemon resumes existing agents when fresh=False."""
        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        await _seed_agent(store, "agent-r1")

        suffering = SufferingState(agent_id="agent-r1")
        suffering.add_stressor(
            StressorType.FUTILITY, "stuck", "complete a goal", initial_severity=0.42,
        )
        cp_mgr = CheckpointManager(hive_dir)
        ctx = ExecutionContext(
            store=store, comms_dir=hive_dir / "comms", memory_dir=hive_dir / "agent_memory",
        )
        cp_mgr.save("agent-r1", "daemon_shutdown", suffering, None, ctx, [])

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs", fresh=False)

        async def _no_run() -> None:
            daemon._running = False

        daemon._run = _no_run  # type: ignore[assignment]

        with patch("hive.daemon.loop.create_runtime_provider", side_effect=_mock_provider):
            await daemon.start()

        restored_suffering = daemon._suffering.get("agent-r1")
        assert restored_suffering is not None
        assert restored_suffering.cumulative_load > 0.0
        assert len(restored_suffering.active) == 1

    @pytest.mark.asyncio
    async def test_fresh_ignores_existing(self, hive_dir: Path) -> None:
        """Daemon with fresh=True does not restore suffering from checkpoints."""
        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        await _seed_agent(store, "agent-f1")

        suffering = SufferingState(agent_id="agent-f1")
        suffering.add_stressor(
            StressorType.FUTILITY, "stuck", "complete a goal", initial_severity=0.75,
        )
        cp_mgr = CheckpointManager(hive_dir)
        ctx = ExecutionContext(
            store=store, comms_dir=hive_dir / "comms", memory_dir=hive_dir / "agent_memory",
        )
        cp_mgr.save("agent-f1", "daemon_shutdown", suffering, None, ctx, [])

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs", fresh=True)

        async def _no_run() -> None:
            daemon._running = False

        daemon._run = _no_run  # type: ignore[assignment]

        with patch("hive.daemon.loop.create_runtime_provider", side_effect=_mock_provider):
            await daemon.start()

        restored = daemon._suffering.get("agent-f1")
        if restored is not None:
            assert restored.cumulative_load == 0.0

    @pytest.mark.asyncio
    async def test_resume_abandons_stale_goals(self, hive_dir: Path) -> None:
        """Stale active goals are abandoned on resume."""
        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        await _seed_agent(store, "agent-s1")
        await store.save_goal("stale-goal", "agent-s1", "Was mid-execution")

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs", fresh=False)

        async def _no_run() -> None:
            daemon._running = False

        daemon._run = _no_run  # type: ignore[assignment]

        with patch("hive.daemon.loop.create_runtime_provider", side_effect=_mock_provider):
            await daemon.start()

        active = await store.get_active_goal("agent-s1")
        assert active is None

        goals = await store.list_agent_goals("agent-s1")
        assert goals[0]["status"] == "abandoned"
