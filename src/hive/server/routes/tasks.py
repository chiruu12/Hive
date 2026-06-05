"""Task execution endpoints: run-now (sync), SSE stream, and goal listing."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from hive.runtime.types import Task
from hive.server.deps import ServerContext, get_context, get_user, resolve_agent_id
from hive.server.runner import build_oneshot_agent
from hive.server.schemas import TaskRequest, TaskResponse
from hive.server.streaming import stream_task

router = APIRouter(prefix="/agents", tags=["tasks"])


@router.post("/{agent_id}/tasks", response_model=TaskResponse)
async def run_task(
    agent_id: str,
    body: TaskRequest,
    ctx: ServerContext = Depends(get_context),
    user: str = Depends(get_user),
) -> TaskResponse:
    """Run a single task on an agent now, independent of the heartbeat loop."""
    resolved = await resolve_agent_id(ctx.store, agent_id)
    agent = await ctx.store.get_agent(resolved)
    assert agent is not None
    session_id = await ctx.sessions.resolve(
        user, resolved, body.instruction, body.session_id, body.session_key
    )
    runtime_agent = build_oneshot_agent(ctx, agent, session_id)
    result = await runtime_agent.run(Task(instruction=body.instruction, max_steps=body.max_steps))

    return TaskResponse(
        task_id=result.task_id,
        status=result.status.value,
        output=result.output,
        steps_taken=result.steps_taken,
        tool_calls_made=result.tool_calls_made,
        session_id=session_id,
        approval_ids=list(result.approval_ids),
    )


@router.post("/{agent_id}/tasks/stream")
async def stream_task_endpoint(
    agent_id: str,
    body: TaskRequest,
    ctx: ServerContext = Depends(get_context),
    user: str = Depends(get_user),
) -> EventSourceResponse:
    """Run a task and stream token deltas over Server-Sent Events."""
    resolved = await resolve_agent_id(ctx.store, agent_id)
    agent = await ctx.store.get_agent(resolved)
    assert agent is not None
    session_id = await ctx.sessions.resolve(
        user, resolved, body.instruction, body.session_id, body.session_key
    )
    return EventSourceResponse(
        stream_task(ctx, agent, body.instruction, session_id, body.max_steps)
    )


@router.get("/{agent_id}/goals")
async def list_goals(
    agent_id: str, limit: int = 20, ctx: ServerContext = Depends(get_context)
) -> list[dict[str, Any]]:
    resolved = await resolve_agent_id(ctx.store, agent_id)
    return await ctx.store.list_agent_goals(resolved, limit=limit)
