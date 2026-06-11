"""Human-in-the-loop approval endpoints: list pending and approve/deny.

Trust boundary: the REST API has no built-in authentication and agents are a single
shared pool in this release (not owned per user), so ``X-Hive-User`` is a routing
hint, not a security control. The approval queue is therefore a shared operator
surface -- run the server behind your own auth/proxy for multi-tenant use. Per-agent
scoping on resolve (below) is a correctness guard, not an authorization boundary.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from hive.server.deps import ServerContext, get_context, get_user, resolve_agent_id
from hive.server.schemas import ApprovalDecisionRequest, ApprovalSummary

router = APIRouter(tags=["approvals"])


def _to_summary(row: dict[str, Any]) -> ApprovalSummary:
    return ApprovalSummary(
        approval_id=row["approval_id"],
        agent_id=row["agent_id"],
        tool_name=row["tool_name"],
        arguments=row["arguments"],
        status=row["status"],
        created_at=row["created_at"],
        session_id=row.get("session_id"),
        goal_id=row.get("goal_id"),
        reason=row.get("reason"),
        resolved_by=row.get("resolved_by"),
    )


@router.get("/approvals", response_model=list[ApprovalSummary])
async def list_pending_approvals(
    ctx: ServerContext = Depends(get_context),
    limit: int | None = Query(None, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[ApprovalSummary]:
    """Global pending-approval review queue across all agents."""
    rows = await ctx.store.list_all_pending_approvals(limit=limit, offset=offset)
    return [_to_summary(r) for r in rows]


@router.get("/agents/{agent_id}/approvals", response_model=list[ApprovalSummary])
async def list_agent_approvals(
    agent_id: str,
    ctx: ServerContext = Depends(get_context),
    limit: int | None = Query(None, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[ApprovalSummary]:
    resolved = await resolve_agent_id(ctx.store, agent_id)
    rows = await ctx.store.get_pending_approvals(resolved, limit=limit, offset=offset)
    return [_to_summary(r) for r in rows]


@router.post("/agents/{agent_id}/approvals/{approval_id}", response_model=ApprovalSummary)
async def resolve_approval(
    agent_id: str,
    approval_id: str,
    body: ApprovalDecisionRequest,
    ctx: ServerContext = Depends(get_context),
    user: str = Depends(get_user),
) -> ApprovalSummary:
    """Approve or deny a pending tool call. Returns 409 if already resolved."""
    decision = body.decision.lower()
    if decision not in ("approve", "deny"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'deny'")
    resolved = await resolve_agent_id(ctx.store, agent_id)
    status = "approved" if decision == "approve" else "denied"
    # Scope the resolution to the agent in the URL so a pending approval belonging to
    # a different agent can't be approved/denied via a guessed id under this path.
    ok = await ctx.store.resolve_approval(
        approval_id, status, resolved_by=user, reason=body.reason, agent_id=resolved
    )
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="approval not pending, does not exist, or does not belong to this agent",
        )
    row = await ctx.store.get_approval(approval_id)
    assert row is not None
    return _to_summary(row)
