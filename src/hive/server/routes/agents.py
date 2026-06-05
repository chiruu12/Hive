"""Agent lifecycle endpoints: spawn, list, get, kill, nudge."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends

from hive.agents.profile import AgentProfile, default_profiles_dir
from hive.agents.state import AgentState, AgentStatus
from hive.server.deps import ServerContext, get_context, resolve_agent_id
from hive.server.schemas import (
    AgentSummary,
    NudgeRequest,
    SpawnRequest,
    SpawnResponse,
)

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("", response_model=SpawnResponse, status_code=201)
async def spawn_agent(
    body: SpawnRequest, ctx: ServerContext = Depends(get_context)
) -> SpawnResponse:
    """Spawn an agent from a preset profile (mirrors ``hive spawn``)."""
    profile = AgentProfile.from_preset(body.preset, default_profiles_dir())
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
async def list_agents(ctx: ServerContext = Depends(get_context)) -> list[AgentSummary]:
    agents = await ctx.store.list_agents()
    summaries: list[AgentSummary] = []
    for a in agents:
        goal = await ctx.store.get_active_goal(a.agent_id)
        summaries.append(
            AgentSummary(
                agent_id=a.agent_id,
                name=a.name,
                role=a.role,
                model=a.model,
                status=a.status.value,
                goal=goal["objective"] if goal else None,
            )
        )
    return summaries


@router.get("/{agent_id}", response_model=AgentSummary)
async def get_agent(agent_id: str, ctx: ServerContext = Depends(get_context)) -> AgentSummary:
    resolved = await resolve_agent_id(ctx.store, agent_id)
    a = await ctx.store.get_agent(resolved)
    assert a is not None  # resolve_agent_id guarantees existence
    goal = await ctx.store.get_active_goal(resolved)
    return AgentSummary(
        agent_id=a.agent_id,
        name=a.name,
        role=a.role,
        model=a.model,
        status=a.status.value,
        goal=goal["objective"] if goal else None,
    )


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
    return {"nudge_id": nudge_id}
