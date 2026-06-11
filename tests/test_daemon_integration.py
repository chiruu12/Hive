"""Integration test — daemon loop end-to-end with mocked LLM."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from hive.agents.state import AgentState, AgentStatus
from hive.config import HiveConfig, set_config
from hive.daemon.loop import HiveDaemon
from hive.memory.store import HiveStore
from hive.models.base import BaseProvider
from hive.runtime.types import GenerateResult, Message, ToolCall


class MockDaemonProvider(BaseProvider):
    """Provider that returns a goal JSON for existence loop, then tool calls for pursuit."""

    def __init__(self) -> None:
        super().__init__("mock-model")
        self._call_count = 0

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
        self._call_count += 1
        prompt = " ".join(m.content for m in messages).lower()

        if "what is the single most valuable" in prompt or "your task" in prompt:
            content = json.dumps(
                {
                    "goal": "Research Python testing best practices",
                    "reasoning": "Testing knowledge helps the team",
                }
            )
            msg = Message.assistant(content)
        elif tools:
            msg = Message.assistant(
                "I'll store my findings.",
                [
                    ToolCall(
                        id=f"tc-{self._call_count}",
                        name="memory_set",
                        arguments={"key": "research", "value": "pytest is great"},
                    )
                ],
            )
        else:
            msg = Message.assistant("Done researching.")

        return GenerateResult(
            message=msg,
            model="mock-model",
            input_tokens=50,
            output_tokens=20,
            cost_usd=0.0001,
            duration_ms=100,
        )

    async def generate_structured(
        self,
        messages: list[Message],
        output_type: type[Any],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Any:
        raise NotImplementedError("MockDaemonProvider does not support structured output")


def _mock_create_provider(model_name: str) -> MockDaemonProvider:
    return MockDaemonProvider()


@pytest.fixture
def hive_dir(tmp_path: Path) -> Path:
    """Set up a minimal .hive directory."""
    hive = tmp_path / ".hive"
    hive.mkdir()
    (hive / "sessions").mkdir()
    (hive / "workspaces").mkdir()
    (hive / "comms").mkdir()
    (hive / "agent_memory").mkdir()

    cfg = HiveConfig()
    cfg.economy.enabled = False
    set_config(cfg)
    cfg.save(hive)

    return hive


async def _seed_agent(store: HiveStore, name: str = "researcher") -> AgentState:
    """Create a test agent in the database."""
    state = AgentState(
        agent_id=f"{name}-test0001",
        name=name,
        role="research assistant",
        model="mock-model",
        status=AgentStatus.IDLE,
        workspace=".",
    )
    await store.save_agent(state)
    return state


class TestDaemonIntegration:
    @pytest.mark.asyncio
    async def test_full_cycle(self, hive_dir: Path) -> None:
        """Daemon runs 2 cycles: generates goal, pursues it, updates state."""
        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        agent = await _seed_agent(store)

        logs_dir = hive_dir.parent / "logs"
        daemon = HiveDaemon(
            hive_dir,
            heartbeat=0,
            logs_dir=logs_dir,
            profiles=["researcher"],
        )

        # Drive just the agent-cycle path for 2 cycles in isolation (no economy /
        # swarm), so the test stays deterministic and provider-mocked.
        cycles_run = 0

        async def _limited_run(max_cycles: int | None = None) -> None:
            nonlocal cycles_run
            while daemon._running and cycles_run < 2:
                daemon._cycle_count += 1
                cycles_run += 1
                agents = await daemon._store.list_agents()
                alive = [a for a in agents if a.is_alive()]
                for a in alive:
                    await daemon._run_agent_cycle(a)
            daemon._running = False

        daemon._run = _limited_run  # type: ignore[assignment]

        with patch(
            "hive.daemon.loop.create_runtime_provider",
            side_effect=_mock_create_provider,
        ):
            await daemon.start()

        agents = await store.list_agents()
        assert len(agents) == 1
        assert agents[0].agent_id == agent.agent_id

        goals = await store.list_agent_goals(agent.agent_id, limit=10)
        assert len(goals) >= 1
        assert any("research" in g.get("objective", "").lower() for g in goals)

    @pytest.mark.asyncio
    async def test_pursuit_writes_decision_and_tool_logs(self, hive_dir: Path) -> None:
        """Goal pursuit emits DecisionLog/ToolLog entries correlated to the goal.

        Regression test: the daemon's pursuit Agent used to be constructed
        without a log_writer, so pursuit decisions and tool calls were never
        logged at all.
        """
        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        agent = await _seed_agent(store)

        logs_dir = hive_dir.parent / "logs"
        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=logs_dir, profiles=["researcher"])

        cycles_run = 0

        async def _limited_run(max_cycles: int | None = None) -> None:
            nonlocal cycles_run
            while daemon._running and cycles_run < 2:
                daemon._cycle_count += 1
                cycles_run += 1
                agents = await daemon._store.list_agents()
                for a in [a for a in agents if a.is_alive()]:
                    await daemon._run_agent_cycle(a)
            daemon._running = False

        daemon._run = _limited_run  # type: ignore[assignment]

        with patch(
            "hive.daemon.loop.create_runtime_provider",
            side_effect=_mock_create_provider,
        ):
            await daemon.start()

        decision_files = list(logs_dir.glob(f"runs/*/agents/{agent.agent_id}/decisions.jsonl"))
        tool_files = list(logs_dir.glob(f"runs/*/agents/{agent.agent_id}/tools.jsonl"))
        assert decision_files, "pursuit wrote no decisions.jsonl"
        assert tool_files, "pursuit wrote no tools.jsonl"

        goals = await store.list_agent_goals(agent.agent_id, limit=10)
        goal_ids = {g["goal_id"] for g in goals}

        decisions = [json.loads(line) for line in decision_files[0].read_text().splitlines()]
        pursuit = [d for d in decisions if d.get("goal_id")]
        assert pursuit, "no decision carries a goal_id"
        assert pursuit[0]["goal_id"] in goal_ids
        assert pursuit[0]["step_index"] >= 1

        tools = [json.loads(line) for line in tool_files[0].read_text().splitlines()]
        assert tools[0]["goal_id"] in goal_ids
        assert tools[0]["step_index"] >= 1

    @pytest.mark.asyncio
    async def test_goal_generation(self, hive_dir: Path) -> None:
        """ExistenceLoop generates a goal via the mocked provider."""
        from hive.agents.existence import ExistenceLoop
        from hive.agents.profile import AgentProfile
        from hive.agents.suffering import SufferingState
        from hive.memory.events import EventLog

        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()

        provider = MockDaemonProvider()
        profile = AgentProfile(name="researcher", role="research assistant")
        suffering = SufferingState(agent_id="test-001")

        existence = ExistenceLoop(
            agent_id="test-001",
            profile=profile,
            provider=provider,
            store=store,
            event_log=EventLog(hive_dir),
            hive_dir=hive_dir,
            economy_enabled=False,
            tools_description="- memory_set(key, value): Store a value",
        )

        goal = await existence.generate_goal(suffering, [], [])
        assert goal is not None
        assert "research" in goal.lower()

        goals = await store.list_agent_goals("test-001", limit=5)
        assert len(goals) == 1
        assert goals[0]["status"] == "active"

    @pytest.mark.asyncio
    async def test_suffering_tracked(self, hive_dir: Path) -> None:
        """Suffering state updates across cycles."""
        from hive.agents.suffering import SufferingState

        suffering = SufferingState(agent_id="test-suf")
        assert suffering.cumulative_load == 0.0

        suffering.escalate_all()
        assert suffering.cumulative_load == 0.0

        from hive.agents.suffering import assess_conditions

        assess_conditions(suffering, recent_completed=0, recent_failed=3, total_steps=1)
        suffering.escalate_all()
        assert suffering.cumulative_load > 0.0

    @pytest.mark.asyncio
    async def test_events_written(self, hive_dir: Path) -> None:
        """Events are persisted to the event log."""
        from hive.memory.events import EventLog, EventType, HiveEvent

        event_log = EventLog(hive_dir)
        event = HiveEvent(
            event_type=EventType.GOAL_SET,
            agent_id="test-ev",
            session_id="sess-test",
            data={"goal_id": "g-001", "objective": "test goal"},
        )
        await event_log.append(event)

        sessions_dir = hive_dir / "sessions" / "test-ev"
        assert sessions_dir.exists()
        jsonl_files = list(sessions_dir.glob("*.jsonl"))
        assert len(jsonl_files) == 1
        content = jsonl_files[0].read_text().strip()
        assert "test goal" in content
