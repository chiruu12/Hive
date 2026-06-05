"""Tests for human-in-the-loop tool-approval gating in the ReAct loop."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hive.agents.approval import ApprovalPolicy, StoreApprovalGate
from hive.config import ApprovalConfig
from hive.memory.store import HiveStore
from hive.runtime.agent import Agent
from hive.runtime.types import GenerateResult, Message, TaskStatus, ToolCall
from hive.tools import Toolkit, tool
from hive.tools.base import Tool


class MockProvider:
    """Minimal provider returning pre-programmed responses (no streaming)."""

    def __init__(self, responses: list[Message]):
        self._responses = list(responses)
        self._i = 0

    async def generate_with_metadata(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> GenerateResult:
        resp = self._responses[self._i] if self._i < len(self._responses) else Message.assistant(
            "done"
        )
        self._i += 1
        return GenerateResult(message=resp, model="mock", input_tokens=1, output_tokens=1)


class DangerToolkit(Toolkit):
    @tool(requires_approval=True)
    def danger(self, target: str) -> str:
        """Do something that needs approval.

        Args:
            target: What to act on.
        """
        return f"executed on {target}"


def _gate(store: HiveStore, agent_id: str = "a1") -> StoreApprovalGate:
    return StoreApprovalGate(
        store, ApprovalPolicy(ApprovalConfig(enabled=True)), agent_id, cycle_provider=lambda: 1
    )


def _tool_call(name: str = "danger") -> ToolCall:
    return ToolCall(id="tc1", name=name, arguments={"target": "x"})


class TestApprovalPolicy:
    def test_disabled_never_requires(self) -> None:
        t = Tool("danger", "", {}, lambda: None, requires_approval=True)
        assert ApprovalPolicy(ApprovalConfig(enabled=False)).requires_approval(t) is False

    def test_flag_requires_when_enabled(self) -> None:
        t = Tool("danger", "", {}, lambda: None, requires_approval=True)
        assert ApprovalPolicy(ApprovalConfig(enabled=True)).requires_approval(t) is True

    def test_require_for_list_gates_unflagged_tool(self) -> None:
        t = Tool("shell", "", {}, lambda: None)
        cfg = ApprovalConfig(enabled=True, require_for=["shell"])
        assert ApprovalPolicy(cfg).requires_approval(t) is True

    def test_auto_approve_overrides_flag(self) -> None:
        t = Tool("danger", "", {}, lambda: None, requires_approval=True)
        cfg = ApprovalConfig(enabled=True, auto_approve=["danger"])
        assert ApprovalPolicy(cfg).requires_approval(t) is False


class TestRuntimeGating:
    @pytest.mark.asyncio
    async def test_pending_pauses_run_and_records_approval(self, tmp_path: Path) -> None:
        store = HiveStore(tmp_path / "s.db")
        await store.initialize()
        agent = Agent(
            name="a1",
            model=MockProvider([Message.assistant("", [_tool_call()])]),  # type: ignore[arg-type]
            toolkits=[DangerToolkit()],
            agent_id="a1",
            approval_gate=_gate(store),
        )
        result = await _run(agent)

        assert result.status == TaskStatus.WAITING_APPROVAL
        pending = await store.get_pending_approvals("a1")
        assert len(pending) == 1 and pending[0]["tool_name"] == "danger"

    @pytest.mark.asyncio
    async def test_approved_then_resume_executes_tool(self, tmp_path: Path) -> None:
        store = HiveStore(tmp_path / "s.db")
        await store.initialize()

        # First run: pauses, creates a pending approval.
        a1 = Agent(
            name="a1",
            model=MockProvider([Message.assistant("", [_tool_call()])]),  # type: ignore[arg-type]
            toolkits=[DangerToolkit()],
            agent_id="a1",
            approval_gate=_gate(store),
        )
        r1 = await _run(a1)
        assert r1.status == TaskStatus.WAITING_APPROVAL
        approval_id = (await store.get_pending_approvals("a1"))[0]["approval_id"]

        # Human approves.
        assert await store.resolve_approval(approval_id, "approved", resolved_by="user") is True

        # Resume: fresh ReAct attempt (tool_call again, then a final answer).
        a2 = Agent(
            name="a1",
            model=MockProvider(  # type: ignore[arg-type]
                [Message.assistant("", [_tool_call()]), Message.assistant("all done")]
            ),
            toolkits=[DangerToolkit()],
            agent_id="a1",
            approval_gate=_gate(store),
        )
        r2 = await _run(a2)
        assert r2.status == TaskStatus.COMPLETED
        assert r2.output == "all done"
        # The grant was single-use (consumed), so nothing is left pending.
        assert await store.get_pending_approvals("a1") == []

    @pytest.mark.asyncio
    async def test_denied_surfaces_to_model_and_continues(self, tmp_path: Path) -> None:
        store = HiveStore(tmp_path / "s.db")
        await store.initialize()
        a1 = Agent(
            name="a1",
            model=MockProvider([Message.assistant("", [_tool_call()])]),  # type: ignore[arg-type]
            toolkits=[DangerToolkit()],
            agent_id="a1",
            approval_gate=_gate(store),
        )
        await _run(a1)
        approval_id = (await store.get_pending_approvals("a1"))[0]["approval_id"]
        await store.resolve_approval(approval_id, "denied", resolved_by="user", reason="nope")

        a2 = Agent(
            name="a1",
            model=MockProvider(  # type: ignore[arg-type]
                [Message.assistant("", [_tool_call()]), Message.assistant("understood")]
            ),
            toolkits=[DangerToolkit()],
            agent_id="a1",
            approval_gate=_gate(store),
        )
        r2 = await _run(a2)
        # Denied tool does not execute; the model sees the denial and finishes.
        assert r2.status == TaskStatus.COMPLETED
        assert r2.output == "understood"


async def _run(agent: Agent) -> Any:
    from hive.runtime.types import Task

    return await agent.run(Task(instruction="do it"))
