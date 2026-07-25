"""Phase 1 restart continuity: preserve active goals and pursuit transcripts."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from hive.agents.state import AgentState, AgentStatus
from hive.config import HiveConfig, set_config
from hive.daemon.loop import HiveDaemon
from hive.memory.pursuit_transcript import PursuitTranscriptStore
from hive.memory.store import HiveStore
from hive.models.base import BaseProvider
from hive.runtime.types import GenerateResult, Message, Role, ToolCall


class _PartialPursuitProvider(BaseProvider):
    """Runs tool loops until resume marker visible, then completes."""

    MARKER = "memory_set-result"

    def __init__(self) -> None:
        super().__init__("mock-restart")
        self.calls = 0
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
        self.calls += 1
        self.seen_messages.append(list(messages))
        resumed = any(
            m.role == Role.SYSTEM and "updated pursuit context" in m.content.lower()
            for m in messages
        )
        transcript = " ".join(m.content for m in messages)
        if resumed and self.MARKER in transcript:
            return GenerateResult(message=Message.assistant("done after restart"), model="mock")
        if tools:
            return GenerateResult(
                message=Message.assistant(
                    "working",
                    [
                        ToolCall(
                            id=f"tc-{self.calls}",
                            name="memory_set",
                            arguments={"key": "k", "value": "v"},
                        )
                    ],
                ),
                model="mock",
            )
        return GenerateResult(message=Message.assistant("done"), model="mock")


def _mock_provider(model_name: str) -> _PartialPursuitProvider:
    return _PartialPursuitProvider()


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


async def _seed_agent(store: HiveStore, agent_id: str = "researcher-test0001") -> AgentState:
    state = AgentState(
        agent_id=agent_id,
        name="researcher",
        role="research assistant",
        model="mock-model",
        status=AgentStatus.IDLE,
        workspace=".",
    )
    await store.save_agent(state)
    return state


async def _ready_daemon(
    hive_dir: Path,
    *,
    profiles_dir: Path,
    logs_dir: Path,
) -> tuple[HiveDaemon, HiveStore]:
    cfg = HiveConfig.load(hive_dir)
    cfg.profiles_dir = str(profiles_dir)
    cfg.daemon.max_steps_policy = "continue"
    cfg.daemon.pursuit_resume = True
    set_config(cfg)
    cfg.save(hive_dir)

    daemon = HiveDaemon(
        hive_dir,
        heartbeat=1,
        logs_dir=logs_dir,
        profiles=["researcher"],
    )
    store = daemon._store
    await store.initialize()
    daemon._log.start_run(heartbeat=1, profiles=["researcher"], agents=[], tools=[])
    return daemon, store


@pytest.mark.asyncio
async def test_restart_preserves_goal_and_transcript(hive_dir: Path, tmp_path: Path) -> None:
    """Stop/start via shutdown + resume keeps active goal and pursuit transcript."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "researcher.yaml").write_text(
        "name: researcher\nrole: test\nmodel: mock-model\nmax_steps: 2\n"
    )
    logs1 = tmp_path / "logs1"
    logs2 = tmp_path / "logs2"

    store = HiveStore(hive_dir / "hive.db")
    await store.initialize()
    agent = await _seed_agent(store)
    goal_id = "g-restart-cont"
    await store.save_goal(goal_id, agent.agent_id, "Persist across restart")

    daemon1, _ = await _ready_daemon(hive_dir, profiles_dir=profiles, logs_dir=logs1)

    with patch("hive.daemon.loop.create_runtime_provider", side_effect=_mock_provider):
        await daemon1._run_agent_cycle(agent)

    transcript_store = PursuitTranscriptStore(store)
    before_shutdown = await transcript_store.load_messages(goal_id, agent.agent_id)
    assert before_shutdown
    before_count = len(before_shutdown)

    active = await store.get_active_goal(agent.agent_id)
    assert active is not None
    assert active["goal_id"] == goal_id

    daemon1._running = False
    with patch("hive.daemon.loop.create_runtime_provider", side_effect=_mock_provider):
        await daemon1._shutdown()

    active_after_shutdown = await store.get_active_goal(agent.agent_id)
    assert active_after_shutdown is not None
    assert active_after_shutdown["goal_id"] == goal_id

    after_shutdown_msgs = await transcript_store.load_messages(goal_id, agent.agent_id)
    assert len(after_shutdown_msgs) == before_count

    daemon2, _ = await _ready_daemon(hive_dir, profiles_dir=profiles, logs_dir=logs2)
    with patch("hive.daemon.loop.create_runtime_provider", side_effect=_mock_provider):
        await daemon2._resume_agents()

    active_after_resume = await store.get_active_goal(agent.agent_id)
    assert active_after_resume is not None
    assert active_after_resume["goal_id"] == goal_id

    after_resume_msgs = await transcript_store.load_messages(goal_id, agent.agent_id)
    assert len(after_resume_msgs) >= before_count

    provider_holder: dict[str, _PartialPursuitProvider] = {}

    def _factory(model_name: str) -> _PartialPursuitProvider:
        provider = _PartialPursuitProvider()
        provider_holder["p"] = provider
        return provider

    agent = await store.get_agent(agent.agent_id)
    assert agent is not None
    with patch("hive.daemon.loop.create_runtime_provider", side_effect=_factory):
        await daemon2._run_agent_cycle(agent)

    resumed_turn = provider_holder["p"].seen_messages[0]
    transcript = " ".join(m.content for m in resumed_turn)
    assert (
        "updated pursuit context" in transcript.lower()
        or _PartialPursuitProvider.MARKER in transcript
    )
