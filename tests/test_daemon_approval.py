"""Daemon-level human-in-the-loop: park on pending approval, resume on resolve.

Drives ``_run_agent_cycle`` directly (one call == one heartbeat) rather than
``start()``, because ``start()``'s resume path abandons active goals -- which would
also discard a parked agent's goal between restarts. Per-cycle control lets us
assert the park/resume transitions precisely.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from hive.agents.state import AgentState, AgentStatus
from hive.config import HiveConfig, set_config
from hive.daemon.loop import HiveDaemon
from hive.memory.store import HiveStore
from hive.models.base import BaseProvider
from hive.runtime.types import GenerateResult, Message, Role, ToolCall


class GatedToolProvider(BaseProvider):
    """Calls gated ``memory_set`` until its real result appears, then finishes.

    Content-based (not a counter) so it behaves correctly across the daemon's
    provider cache and across fresh per-cycle conversations.
    """

    def __init__(self) -> None:
        super().__init__("mock")

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
        executed = any(
            m.role == Role.TOOL and m.name == "memory_set" and not m.is_error for m in messages
        )
        if tools and not executed:
            msg = Message.assistant(
                "Storing.",
                [ToolCall(id="tc-1", name="memory_set", arguments={"key": "k", "value": "v"})],
            )
        else:
            msg = Message.assistant("Done.")
        return GenerateResult(message=msg, model="mock", input_tokens=5, output_tokens=2)

    async def generate_structured(
        self, messages: list[Message], output_type: type[Any], **kw: Any
    ) -> Any:
        raise NotImplementedError


def _mock_provider(model_name: str) -> GatedToolProvider:
    return GatedToolProvider()


@pytest.fixture
def hive_dir(tmp_path: Path) -> Path:
    hive = tmp_path / ".hive"
    hive.mkdir()
    for d in ["sessions", "workspaces", "comms", "agent_memory", "checkpoints"]:
        (hive / d).mkdir()
    cfg = HiveConfig()
    cfg.economy.enabled = False
    cfg.approval.enabled = True
    cfg.approval.require_for = ["memory_set"]
    set_config(cfg)
    cfg.save(hive)
    return hive


async def _make_ready_daemon(hive_dir: Path) -> tuple[HiveDaemon, HiveStore, str]:
    daemon = HiveDaemon(hive_dir, heartbeat=1)
    store = daemon._store
    await store.initialize()
    agent_id = "coder-appr01"
    await store.save_agent(
        AgentState(
            agent_id=agent_id,
            name="coder",
            role="developer",
            model="mock",
            status=AgentStatus.IDLE,
            workspace=".",
        )
    )
    await store.save_goal("g1", agent_id, "store something useful")
    daemon._log.start_run(heartbeat=1, profiles=[], agents=[agent_id], tools=[])
    return daemon, store, agent_id


async def _cycle(daemon: HiveDaemon, store: HiveStore, agent_id: str) -> str:
    """Run one heartbeat for the agent using its current persisted state."""
    daemon._cycle_count += 1
    agent = await store.get_agent(agent_id)
    assert agent is not None
    return await daemon._run_agent_cycle(agent)


@pytest.mark.asyncio
async def test_daemon_parks_then_resumes_on_approval(hive_dir: Path) -> None:
    with patch("hive.daemon.loop.create_runtime_provider", side_effect=_mock_provider):
        daemon, store, agent_id = await _make_ready_daemon(hive_dir)

        # Cycle 1: the gated tool pauses the agent.
        assert await _cycle(daemon, store, agent_id) == "waiting_approval"
        agent = await store.get_agent(agent_id)
        assert agent is not None and agent.status == AgentStatus.WAITING
        pending = await store.get_pending_approvals(agent_id)
        assert len(pending) == 1 and pending[0]["tool_name"] == "memory_set"
        assert await store.get_active_goal(agent_id) is not None  # goal still active

        # Human approves.
        await store.resolve_approval(pending[0]["approval_id"], "approved", resolved_by="test")

        # Cycle 2: un-parks, runs the tool, completes the goal.
        assert await _cycle(daemon, store, agent_id) == "completed"
        assert await store.get_pending_approvals(agent_id) == []
        assert await store.get_active_goal(agent_id) is None  # completed


@pytest.mark.asyncio
async def test_daemon_stays_parked_while_pending(hive_dir: Path) -> None:
    with patch("hive.daemon.loop.create_runtime_provider", side_effect=_mock_provider):
        daemon, store, agent_id = await _make_ready_daemon(hive_dir)

        assert await _cycle(daemon, store, agent_id) == "waiting_approval"
        # A second cycle without resolving returns early via the park gate and does
        # not create a duplicate request.
        assert await _cycle(daemon, store, agent_id) == "waiting_approval"

        assert len(await store.get_pending_approvals(agent_id)) == 1
        agent = await store.get_agent(agent_id)
        assert agent is not None and agent.status == AgentStatus.WAITING
