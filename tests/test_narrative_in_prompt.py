"""The goal-pursuing runtime agent must see its persistent identity narrative.

Regression for the gap where AgentIdentity.narrative was built/truncated but only
fed to goal *generation*, never to the agent actually *pursuing* a goal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from hive.agents.identity import IdentityManager
from hive.agents.profile import AgentProfile
from hive.agents.state import AgentState, AgentStatus
from hive.config import HiveConfig, set_config
from hive.daemon.loop import HiveDaemon
from hive.memory.store import HiveStore
from hive.models.base import BaseProvider
from hive.runtime.types import GenerateResult, Message

_MARKER = "SENTINEL_NARRATIVE_MARKER"


class CapturingProvider(BaseProvider):
    """Records every prompt it receives; completes goals immediately (no tools)."""

    def __init__(self) -> None:
        super().__init__("mock-model")
        self.prompts: list[str] = []

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
        self.prompts.append("\n".join(m.content for m in messages))
        return GenerateResult(
            message=Message.assistant("Done."),
            model="mock-model",
            input_tokens=1,
            output_tokens=1,
            cost_usd=0.0,
            duration_ms=1,
        )

    async def generate_structured(
        self,
        messages: list[Message],
        output_type: type[Any],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Any:
        raise NotImplementedError


@pytest.fixture
def hive_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # chdir into the tmp dir: driving _run_agent_cycle directly uses a LogWriter
    # whose run dir isn't set (no start_run), so it would otherwise write
    # agents/<id>/*.jsonl relative to the repo cwd. Keep that inside tmp.
    monkeypatch.chdir(tmp_path)
    hive = tmp_path / ".hive"
    for sub in ("sessions", "workspaces", "comms", "agent_memory"):
        (hive / sub).mkdir(parents=True)
    cfg = HiveConfig()
    cfg.economy.enabled = False
    set_config(cfg)
    cfg.save(hive)
    return hive


@pytest.mark.asyncio
async def test_pursuit_prompt_includes_identity_narrative(hive_dir: Path) -> None:
    store = HiveStore(hive_dir / "hive.db")
    await store.initialize()

    agent = AgentState(
        agent_id="researcher-test0001",
        name="researcher",
        role="research assistant",
        model="mock-model",
        status=AgentStatus.IDLE,
        workspace=".",
    )
    await store.save_agent(agent)
    # An active goal forces the pursuit path (not goal generation).
    await store.save_goal("g-1", agent.agent_id, "Summarize the auth module")

    # Give the agent a narrative containing a unique marker.
    idm = IdentityManager(hive_dir)
    idm.create(agent.agent_id, AgentProfile(name="researcher", role="research assistant"))
    idm.update_narrative(agent.agent_id, "auth-work", f"shipped the {_MARKER} module")

    provider = CapturingProvider()
    daemon = HiveDaemon(
        hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs", profiles=["researcher"]
    )

    with patch("hive.daemon.loop.create_runtime_provider", return_value=provider):
        await daemon._run_agent_cycle(agent)

    assert provider.prompts, "provider was never called during pursuit"
    joined = "\n".join(provider.prompts)
    assert _MARKER in joined, "identity narrative was not present in the pursuit prompt"
