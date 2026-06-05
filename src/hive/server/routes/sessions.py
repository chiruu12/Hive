"""Session endpoints for per-user/per-session isolation."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from hive.server.deps import (
    DEFAULT_USER,
    ServerContext,
    get_context,
    get_user,
    resolve_agent_id,
)
from hive.server.schemas import SessionCreateRequest, SessionSummary

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _to_summary(row: dict[str, Any]) -> SessionSummary:
    return SessionSummary(
        session_id=row["session_id"],
        agent_id=row["agent_id"],
        user_id=row.get("user_id"),
        session_key=row.get("session_key"),
        task=row["task"],
        status=row["status"],
        started_at=row.get("started_at"),
    )


@router.post("", response_model=SessionSummary, status_code=201)
async def create_session(
    body: SessionCreateRequest,
    ctx: ServerContext = Depends(get_context),
    user: str = Depends(get_user),
) -> SessionSummary:
    resolved = await resolve_agent_id(ctx.store, body.agent_id)
    session_id = f"sess-{uuid4().hex[:12]}"
    metadata = json.dumps(body.metadata) if body.metadata else None
    await ctx.store.create_session(
        session_id,
        resolved,
        body.task,
        user_id=user,
        session_key=body.session_key,
        metadata=metadata,
    )
    row = await ctx.store.get_session(session_id)
    assert row is not None
    return _to_summary(row)


@router.get("", response_model=list[SessionSummary])
async def list_sessions(
    agent_id: str | None = None,
    ctx: ServerContext = Depends(get_context),
    user: str = Depends(get_user),
) -> list[SessionSummary]:
    resolved = await resolve_agent_id(ctx.store, agent_id) if agent_id else None
    rows = await ctx.store.list_sessions(user_id=user, agent_id=resolved)
    return [_to_summary(r) for r in rows]


@router.get("/{session_id}", response_model=SessionSummary)
async def get_session(
    session_id: str,
    ctx: ServerContext = Depends(get_context),
    user: str = Depends(get_user),
) -> SessionSummary:
    row = await ctx.store.get_session(session_id)
    if row is None or (row.get("user_id") or DEFAULT_USER) != user:
        raise HTTPException(status_code=404, detail="session not found")
    return _to_summary(row)


@router.delete("/{session_id}", status_code=204)
async def close_session(
    session_id: str,
    ctx: ServerContext = Depends(get_context),
    user: str = Depends(get_user),
) -> None:
    row = await ctx.store.get_session(session_id)
    if row is None or (row.get("user_id") or DEFAULT_USER) != user:
        raise HTTPException(status_code=404, detail="session not found")
    await ctx.store.complete_session(session_id)
