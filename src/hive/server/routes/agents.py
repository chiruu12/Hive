"""Agent lifecycle endpoints: spawn, list, get, kill, nudge, edit, pause, resume, history."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from hive.agents.profile import AgentProfile, resolve_profiles_dir
from hive.agents.state import AgentState, AgentStatus
from hive.server.deps import ServerContext, get_context, resolve_agent_id
from hive.server.schemas import (
    AgentSummary,
    NudgeRequest,
    SpawnRequest,
    SpawnResponse,
)

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentUpdateRequest(BaseModel):
    model: str | None = None
    role: str | None = None


@router.post("", response_model=SpawnResponse, status_code=201)
async def spawn_agent(
    body: SpawnRequest, ctx: ServerContext = Depends(get_context)
) -> SpawnResponse:
    """Spawn an agent from a preset profile (mirrors ``hive spawn``)."""
    profile = AgentProfile.from_preset(body.preset, resolve_profiles_dir(ctx.hive_dir))
    if body.model:
        profile.model = body.model
    agent_id = f"{profile.name}-{uuid4().hex[:8]}"
    state = AgentState(
        agent_id=agent_id,
        name=profile.name,
        role=profile.role,
        model=profile.model,
        status=AgentStatus.IDLE,
        workspace=str(ctx.hive_dir / "workspaces" / agent_id),
    )
    await ctx.store.save_agent(state)
    return SpawnResponse(agent_id=agent_id)


@router.get("", response_model=list[AgentSummary])
async def list_agents(
    ctx: ServerContext = Depends(get_context),
    limit: int | None = Query(None, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[AgentSummary]:
    agents = await ctx.store.list_agents(limit=limit, offset=offset)
    goals = await ctx.store.get_active_goals_map()
    return [
        AgentSummary(
            agent_id=a.agent_id,
            name=a.name,
            role=a.role,
            model=a.model,
            status=a.status.value,
            goal=goals.get(a.agent_id),
        )
        for a in agents
    ]


@router.get("/{agent_id}", response_model=AgentSummary)
async def get_agent(agent_id: str, ctx: ServerContext = Depends(get_context)) -> AgentSummary:
    resolved = await resolve_agent_id(ctx.store, agent_id)
    a = await ctx.store.get_agent(resolved)
    if a is None:
        raise HTTPException(status_code=404, detail="agent not found")
    goal = await ctx.store.get_active_goal(resolved)
    return AgentSummary(
        agent_id=a.agent_id,
        name=a.name,
        role=a.role,
        model=a.model,
        status=a.status.value,
        goal=goal["objective"] if goal else None,
    )


@router.patch("/{agent_id}")
async def update_agent(
    agent_id: str, body: AgentUpdateRequest, ctx: ServerContext = Depends(get_context)
) -> dict[str, Any]:
    """Update an agent's model or role."""
    resolved = await resolve_agent_id(ctx.store, agent_id)
    a = await ctx.store.get_agent(resolved)
    if a is None:
        raise HTTPException(status_code=404, detail="agent not found")
    changes = []
    if body.model is not None:
        a.model = body.model
        changes.append(f"model={body.model}")
    if body.role is not None:
        a.role = body.role
        changes.append(f"role={body.role}")
    if not changes:
        raise HTTPException(status_code=400, detail="no fields to update")
    await ctx.store.save_agent(a)
    return {"agent_id": resolved, "changes": changes}


@router.delete("/{agent_id}", status_code=204)
async def kill_agent(agent_id: str, ctx: ServerContext = Depends(get_context)) -> None:
    resolved = await resolve_agent_id(ctx.store, agent_id)
    await ctx.store.update_agent_status(resolved, AgentStatus.DEAD)


@router.post("/{agent_id}/nudge", status_code=202)
async def nudge_agent(
    agent_id: str, body: NudgeRequest, ctx: ServerContext = Depends(get_context)
) -> dict[str, str]:
    resolved = await resolve_agent_id(ctx.store, agent_id)
    nudge_id = f"nudge-{uuid4().hex[:8]}"
    await ctx.store.save_nudge(nudge_id, resolved, body.message)
    from hive.daemon.wakeup import touch_nudge_wake_file

    touch_nudge_wake_file(ctx.hive_dir, nudge_id)
    return {"nudge_id": nudge_id}


@router.post("/{agent_id}/pause", status_code=200)
async def pause_agent(agent_id: str, ctx: ServerContext = Depends(get_context)) -> dict[str, str]:
    """Pause an agent so the daemon skips it until resumed."""
    resolved = await resolve_agent_id(ctx.store, agent_id)
    await ctx.store.update_agent_status(resolved, AgentStatus.PAUSED)
    return {"agent_id": resolved, "status": "paused"}


@router.post("/{agent_id}/resume", status_code=200)
async def resume_agent(agent_id: str, ctx: ServerContext = Depends(get_context)) -> dict[str, str]:
    """Resume a paused agent. Only PAUSED agents are affected -- resuming does
    not resurrect a DEAD agent or un-park one WAITING on an approval."""
    resolved = await resolve_agent_id(ctx.store, agent_id)
    a = await ctx.store.get_agent(resolved)
    if a is None:
        raise HTTPException(status_code=404, detail="agent not found")
    if a.status != AgentStatus.PAUSED:
        raise HTTPException(status_code=409, detail=f"agent is {a.status.value}, not paused")
    await ctx.store.update_agent_status(resolved, AgentStatus.IDLE)
    return {"agent_id": resolved, "status": "idle"}


@router.get("/{agent_id}/history")
async def agent_history(
    agent_id: str,
    ctx: ServerContext = Depends(get_context),
    limit: int = Query(20, ge=1, le=200),
) -> list[dict[str, Any]]:
    """Return an agent's goal history."""
    resolved = await resolve_agent_id(ctx.store, agent_id)
    goals = await ctx.store.list_agent_goals(resolved, limit=limit)
    return goals
