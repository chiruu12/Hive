"""Persistence-backed human-in-the-loop approval gate.

``ApprovalPolicy`` is the pure decision of *whether* a tool needs approval (from
config + the tool's own flag). ``StoreApprovalGate`` is the concrete
``ApprovalGate`` the daemon and API wire into an ``Agent``: it records pending
approvals in the ``approvals`` table so a paused tool survives heartbeat cycles,
and grants are single-use (consumed on first use).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from hive.config import ApprovalConfig
from hive.memory.store import HiveStore
from hive.runtime.approval import ApprovalDecision, ApprovalResult
from hive.tools.base import Tool


@dataclass(frozen=True)
class ApprovalPolicy:
    """Pure policy: does this tool require human approval under ``config``?"""

    config: ApprovalConfig

    def requires_approval(self, tool: Tool) -> bool:
        if not self.config.enabled:
            return False
        if tool.name in self.config.auto_approve:
            return False
        return tool.requires_approval or tool.name in self.config.require_for


def hash_arguments(arguments: dict[str, Any]) -> tuple[str, str]:
    """Return ``(canonical_json, short_hash)`` for a tool call's arguments.

    The hash keys an approval to a specific (tool, args) pair so a grant authorizes
    exactly that call and nothing else.
    """
    canonical = json.dumps(arguments, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return canonical, digest


class StoreApprovalGate:
    """``ApprovalGate`` backed by ``HiveStore`` approvals.

    Bound to one agent. ``check`` resolves an existing matching approval
    (approved -> consume + APPROVED, denied -> consume + DENIED, pending -> PENDING)
    or creates a new pending row (find-or-create, so re-driving the same goal each
    heartbeat never duplicates a request).
    """

    def __init__(
        self,
        store: HiveStore,
        policy: ApprovalPolicy,
        agent_id: str,
        cycle_provider: Callable[[], int] | None = None,
        session_id: str | None = None,
        goal_id: str | None = None,
    ):
        self._store = store
        self._policy = policy
        self._agent_id = agent_id
        self._cycle_provider = cycle_provider
        self._session_id = session_id
        self._goal_id = goal_id

    def requires_approval(self, tool: Tool) -> bool:
        return self._policy.requires_approval(tool)

    async def check(self, tool_name: str, arguments: dict[str, Any]) -> ApprovalResult:
        canonical, args_hash = hash_arguments(arguments)
        existing = await self._store.find_active_approval(self._agent_id, tool_name, args_hash)
        if existing is not None:
            approval_id = existing["approval_id"]
            status = existing["status"]
            if status == "approved":
                await self._store.consume_approval(approval_id)
                return ApprovalResult(ApprovalDecision.APPROVED, approval_id)
            if status == "denied":
                await self._store.consume_approval(approval_id)
                return ApprovalResult(
                    ApprovalDecision.DENIED, approval_id, reason=existing.get("reason")
                )
            return ApprovalResult(ApprovalDecision.PENDING, approval_id)

        approval_id = f"ap-{uuid.uuid4().hex[:12]}"
        cycle = self._cycle_provider() if self._cycle_provider is not None else None
        await self._store.create_approval(
            approval_id=approval_id,
            agent_id=self._agent_id,
            tool_name=tool_name,
            arguments=canonical,
            args_hash=args_hash,
            session_id=self._session_id,
            goal_id=self._goal_id,
            cycle_created=cycle,
        )
        return ApprovalResult(ApprovalDecision.PENDING, approval_id)
