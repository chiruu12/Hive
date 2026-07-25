"""Phase B goal lifecycle: profile limits, MAX_STEPS policy, validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from hive.agents.goal_persistence import save_generated_goal, validate_goal
from hive.agents.goal_strategy import GeneratedGoal, GoalContext, GoalStrategy
from hive.agents.state import AgentState, AgentStatus
from hive.config import HiveConfig, set_config
from hive.daemon.loop import HiveDaemon
from hive.memory.store import HiveStore
from hive.models.base import BaseProvider
from hive.runtime import Agent, DaemonAgentAdapter
from hive.runtime.types import GenerateResult, Message, Role, ToolCall
from hive.tools.base import Toolkit, tool


class _LoopingProvider(BaseProvider):
    """Always requests a tool so the agent never completes within max_steps."""

    def __init__(self) -> None:
        super().__init__("mock-loop")
        self.calls = 0
        self.temperatures: list[float] = []

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
        self.calls += 1
        self.temperatures.append(temperature)
        if tools:
            return GenerateResult(
                message=Message.assistant(
                    "working",
                    [ToolCall(id=f"tc-{self.calls}", name="noop", arguments={})],
                ),
                model="mock-loop",
            )
        return GenerateResult(message=Message.assistant("done"), model="mock-loop")


class _NoopToolkit(Toolkit):
    @tool()
    async def noop(self) -> str:
        """No-op tool."""
        return "ok"


@pytest.mark.asyncio
async def test_profile_max_steps_honored_in_pursuit() -> None:
    provider = _LoopingProvider()
    agent = Agent(
        name="tester",
        model=provider,
        toolkits=[_NoopToolkit()],
        max_steps=3,
        temperature=0.9,
    )
    adapter = DaemonAgentAdapter(agent, "agent-1")
    outcome = await adapter.pursue_goal("Keep working")

    assert outcome.hit_step_limit is True
    assert outcome.success is False
    assert outcome.steps_done == 3
    assert provider.calls == 3
    assert provider.temperatures == [0.9, 0.9, 0.9]


@pytest.mark.asyncio
async def test_bridge_maps_max_steps_to_hit_step_limit() -> None:
    provider = _LoopingProvider()
    agent = Agent(name="tester", model=provider, toolkits=[_NoopToolkit()], max_steps=2)
    adapter = DaemonAgentAdapter(agent, "agent-1")
    outcome = await adapter.pursue_goal("loop")
    assert outcome.hit_step_limit is True
    assert outcome.steps_done == 2


def test_validate_goal_rejects_duplicate_active() -> None:
    recent = [{"objective": "Write comprehensive unit tests", "status": "active"}]
    reason = validate_goal("Write comprehensive unit tests", recent)
    assert reason is not None
    assert "duplicate" in reason


@pytest.mark.asyncio
async def test_save_generated_goal_rejects_duplicate(tmp_path: Path) -> None:
    store = HiveStore(tmp_path / "hive.db")
    await store.initialize()
    await store.save_goal("g1", "a1", "Write comprehensive unit tests")

    saved = await save_generated_goal(
        agent_id="a1",
        objective="Write comprehensive unit tests",
        store=store,
    )
    assert saved is None
    goals = await store.list_agent_goals("a1")
    assert len(goals) == 1


class _FixedGoalStrategy:
    def __init__(self, objective: str) -> None:
        self._objective = objective

    async def generate_goal(self, context: GoalContext) -> GeneratedGoal:
        return GeneratedGoal(objective=self._objective)


class MockDaemonProvider(BaseProvider):
    """Minimal provider for daemon integration tests."""

    MARKER = "memory_set-result"

    def __init__(self) -> None:
        super().__init__("mock-model")
        self._call_count = 0
        self.seen_messages: list[list[Message]] = []

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
        self.seen_messages.append(list(messages))
        prompt = " ".join(m.content for m in messages).lower()
        resumed = any(
            m.role == Role.SYSTEM and "updated pursuit context" in m.content.lower()
            for m in messages
        )
        if "what is the single most valuable" in prompt or "your task" in prompt:
            content = json.dumps(
                {"goal": "Research Python testing best practices", "reasoning": "x"}
            )
            msg = Message.assistant(content)
        elif resumed and ("stored:" in prompt or "tool-ok-cycle-marker" in prompt):
            msg = Message.assistant("done after resume")
        elif tools:
            msg = Message.assistant(
                "loop",
                [
                    ToolCall(
                        id=f"tc-{self._call_count}",
                        name="memory_set",
                        arguments={"key": "k", "value": "v"},
                    )
                ],
            )
        else:
            msg = Message.assistant("done")
        return GenerateResult(message=msg, model="mock-model", cost_usd=0.0001)


def _mock_create_provider(model_name: str) -> MockDaemonProvider:
    return MockDaemonProvider()


async def _seed_agent(store: HiveStore, name: str = "researcher") -> AgentState:
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


async def _ready_daemon(
    hive_dir: Path,
    *,
    profiles_dir: Path | None = None,
    max_steps_policy: str = "continue",
    goal_strategy: Any = None,
    logs_dir: Path | None = None,
) -> tuple[HiveDaemon, HiveStore]:
    if profiles_dir is not None:
        cfg = HiveConfig.load(hive_dir)
        cfg.profiles_dir = str(profiles_dir)
        cfg.daemon.max_steps_policy = max_steps_policy  # type: ignore[assignment]
        set_config(cfg)
        cfg.save(hive_dir)

    daemon = HiveDaemon(
        hive_dir,
        heartbeat=1,
        logs_dir=logs_dir or hive_dir.parent / "logs",
        profiles=["researcher"],
        goal_strategy=goal_strategy,
    )
    store = daemon._store
    await store.initialize()
    daemon._log.start_run(heartbeat=1, profiles=["researcher"], agents=[], tools=[])
    return daemon, store


@pytest.mark.asyncio
async def test_max_steps_continue_keeps_goal_active(hive_dir: Path, tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "researcher.yaml").write_text(
        "name: researcher\nrole: test\nmodel: mock-model\nmax_steps: 2\n"
    )
    logs = tmp_path / "logs"

    store = HiveStore(hive_dir / "hive.db")
    await store.initialize()
    agent = await _seed_agent(store)
    await store.save_goal("g-active", agent.agent_id, "Loop forever on purpose")

    daemon, _ = await _ready_daemon(
        hive_dir,
        profiles_dir=profiles,
        max_steps_policy="continue",
        logs_dir=logs,
    )

    with patch("hive.daemon.loop.create_runtime_provider", side_effect=_mock_create_provider):
        await daemon._run_agent_cycle(agent)

    active = await store.get_active_goal(agent.agent_id)
    assert active is not None
    assert active["goal_id"] == "g-active"
    assert active["status"] == "active"

    goal_logs = list(logs.glob(f"runs/*/agents/{agent.agent_id}/goals.jsonl"))
    assert goal_logs
    events = [json.loads(line) for line in goal_logs[0].read_text().splitlines()]
    assert any(e.get("event") == "max_steps" for e in events)


@pytest.mark.asyncio
async def test_max_steps_abandon_policy(hive_dir: Path, tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "researcher.yaml").write_text(
        "name: researcher\nrole: test\nmodel: mock-model\nmax_steps: 2\n"
    )

    store = HiveStore(hive_dir / "hive.db")
    await store.initialize()
    agent = await _seed_agent(store)
    await store.save_goal("g-active", agent.agent_id, "Loop forever on purpose")

    daemon, _ = await _ready_daemon(
        hive_dir,
        profiles_dir=profiles,
        max_steps_policy="abandon",
    )

    with patch("hive.daemon.loop.create_runtime_provider", side_effect=_mock_create_provider):
        await daemon._run_agent_cycle(agent)

    active = await store.get_active_goal(agent.agent_id)
    assert active is None
    goal = await store.get_goal_by_id("g-active")
    assert goal is not None
    assert goal["status"] == "abandoned"


@pytest.mark.asyncio
async def test_custom_strategy_validation_blocks_duplicate(hive_dir: Path, tmp_path: Path) -> None:
    store = HiveStore(hive_dir / "hive.db")
    await store.initialize()
    agent = await _seed_agent(store)
    duplicate = "Write comprehensive unit tests for the daemon"
    await store.save_goal("g-old", agent.agent_id, duplicate)
    await store.abandon_goal("g-old")

    strategy = _FixedGoalStrategy(duplicate)
    assert isinstance(strategy, GoalStrategy)

    daemon, _ = await _ready_daemon(
        hive_dir,
        goal_strategy=strategy,
        logs_dir=tmp_path / "logs",
    )

    with patch("hive.daemon.loop.create_runtime_provider", side_effect=_mock_create_provider):
        await daemon._run_agent_cycle(agent)

    active = await store.get_active_goal(agent.agent_id)
    assert active is None
    goals = await store.list_agent_goals(agent.agent_id)
    assert all(g["status"] != "active" for g in goals)


@pytest.mark.asyncio
async def test_custom_strategy_skip_validation(hive_dir: Path, tmp_path: Path) -> None:
    class _SkipStrategy(_FixedGoalStrategy):
        skip_validation = True

    store = HiveStore(hive_dir / "hive.db")
    await store.initialize()
    agent = await _seed_agent(store)
    duplicate = "Write comprehensive unit tests for the daemon"
    await store.save_goal("g-old", agent.agent_id, duplicate)
    await store.abandon_goal("g-old")

    daemon, _ = await _ready_daemon(
        hive_dir,
        goal_strategy=_SkipStrategy(duplicate),
        logs_dir=tmp_path / "logs",
    )

    with patch("hive.daemon.loop.create_runtime_provider", side_effect=_mock_create_provider):
        await daemon._run_agent_cycle(agent)

    active = await store.get_active_goal(agent.agent_id)
    assert active is not None
    assert active["objective"] == duplicate


@pytest.mark.asyncio
async def test_pursuit_transcript_continues_across_cycles(hive_dir: Path, tmp_path: Path) -> None:
    """Tool results from cycle N are visible to the provider in cycle N+1."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "researcher.yaml").write_text(
        "name: researcher\nrole: test\nmodel: mock-model\nmax_steps: 2\n"
    )

    store = HiveStore(hive_dir / "hive.db")
    await store.initialize()
    agent = await _seed_agent(store)
    await store.save_goal("g-active", agent.agent_id, "Loop forever on purpose")

    daemon, _ = await _ready_daemon(
        hive_dir,
        profiles_dir=profiles,
        max_steps_policy="continue",
        logs_dir=tmp_path / "logs",
    )

    provider_holder: dict[str, MockDaemonProvider] = {}

    def _provider_factory(model_name: str) -> MockDaemonProvider:
        provider = MockDaemonProvider()
        provider_holder["p"] = provider
        return provider

    with patch("hive.daemon.loop.create_runtime_provider", side_effect=_provider_factory):
        await daemon._run_agent_cycle(agent)
        first_provider = provider_holder["p"]
        assert first_provider._call_count == 2
        calls_after_cycle_one = first_provider._call_count

        await daemon._run_agent_cycle(agent)
        assert first_provider._call_count > calls_after_cycle_one
        resumed_turn = first_provider.seen_messages[calls_after_cycle_one]
        transcript = " ".join(m.content for m in resumed_turn)
        assert "stored:" in transcript.lower()

    from hive.memory.pursuit_transcript import PursuitTranscriptStore

    transcript_store = PursuitTranscriptStore(store)
    saved = await transcript_store.load_messages("g-active", agent.agent_id)
    # Goal may complete on cycle 2; transcript cleared on completion.
    goal = await store.get_goal_by_id("g-active")
    assert goal is not None
    if goal["status"] == "active":
        assert saved
        assert any(m.role.value == "tool" for m in saved)
    else:
        assert goal["status"] == "completed"
        assert saved == []


@pytest.mark.asyncio
async def test_pursuit_transcript_survives_daemon_restart(hive_dir: Path, tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "researcher.yaml").write_text(
        "name: researcher\nrole: test\nmodel: mock-model\nmax_steps: 2\n"
    )

    store = HiveStore(hive_dir / "hive.db")
    await store.initialize()
    agent = await _seed_agent(store)
    await store.save_goal("g-restart", agent.agent_id, "Persist transcript")

    daemon1, _ = await _ready_daemon(
        hive_dir,
        profiles_dir=profiles,
        max_steps_policy="continue",
        logs_dir=tmp_path / "logs",
    )

    with patch("hive.daemon.loop.create_runtime_provider", side_effect=_mock_create_provider):
        await daemon1._run_agent_cycle(agent)

    from hive.memory.pursuit_transcript import PursuitTranscriptStore

    transcript_store = PursuitTranscriptStore(store)
    before_restart = await transcript_store.load_messages("g-restart", agent.agent_id)
    assert before_restart

    daemon2, _ = await _ready_daemon(
        hive_dir,
        profiles_dir=profiles,
        max_steps_policy="continue",
        logs_dir=tmp_path / "logs2",
    )

    provider_holder: dict[str, MockDaemonProvider] = {}

    def _provider_factory(model_name: str) -> MockDaemonProvider:
        provider = MockDaemonProvider()
        provider_holder["p"] = provider
        return provider

    with patch("hive.daemon.loop.create_runtime_provider", side_effect=_provider_factory):
        await daemon2._run_agent_cycle(agent)

    resumed = provider_holder["p"].seen_messages[0]
    transcript = " ".join(m.content for m in resumed)
    assert "stored:" in transcript.lower()
