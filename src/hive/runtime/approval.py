"""Human-in-the-loop tool-approval primitives for the agent runtime.

This module is intentionally store-agnostic: it defines only the protocol the
``Agent`` calls and the value types it exchanges. A concrete, persistence-backed
implementation lives in ``hive.agents.approval`` (``StoreApprovalGate``), so the
runtime never imports the database layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from hive.tools.base import Tool


class ApprovalDecision(StrEnum):
    """Outcome of consulting an ApprovalGate for a single tool call."""

    APPROVED = "approved"
    DENIED = "denied"
    PENDING = "pending"


@dataclass(frozen=True)
class ApprovalResult:
    """An ApprovalGate's verdict for one tool call."""

    decision: ApprovalDecision
    approval_id: str
    reason: str | None = None


@runtime_checkable
class ApprovalGate(Protocol):
    """Decides whether a tool call may run, may be denied, or must wait for a human.

    Implementations persist pending approvals so the verdict survives across the
    daemon's heartbeat cycles (agents are records, not live coroutines).
    """

    def requires_approval(self, tool: Tool) -> bool:
        """Whether this tool must pass through the gate before executing."""
        ...

    async def check(self, tool_name: str, arguments: dict[str, Any]) -> ApprovalResult:
        """Resolve (or create) the approval for this exact tool call."""
        ...


class AwaitingApprovalSignal(Exception):  # noqa: N818 -- control-flow signal, not an error
    """Raised inside the ReAct loop when one or more tool calls await approval.

    Carries the pending approval ids so ``Agent.run`` can surface them in the
    ``TaskResult`` and the daemon can park the agent until they are resolved.
    """

    def __init__(self, approval_ids: list[str]):
        self.approval_ids = approval_ids
        super().__init__(f"Awaiting human approval: {', '.join(approval_ids)}")
