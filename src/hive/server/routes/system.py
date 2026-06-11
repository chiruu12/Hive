"""System endpoints: status, health, and run-log listing."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from hive.server.deps import ServerContext, get_context

router = APIRouter(tags=["system"])


@router.get("/status")
async def status(ctx: ServerContext = Depends(get_context)) -> list[dict[str, Any]]:
    """Status of all agents (mirrors ``hive status``)."""
    agents = await ctx.store.list_agents()
    goals = await ctx.store.get_active_goals_map()
    return [
        {
            "agent_id": a.agent_id,
            "name": a.name,
            "role": a.role,
            "model": a.model,
            "status": a.status.value,
            "goal": goals.get(a.agent_id),
        }
        for a in agents
    ]


@router.get("/healthz")
async def healthz(response: Response, ctx: ServerContext = Depends(get_context)) -> dict[str, Any]:
    """Liveness + readiness (DB reachable).

    Returns 503 when the database is unreachable so container/orchestrator probes
    (e.g. the image's HEALTHCHECK) actually detect a degraded instance.
    """
    try:
        await ctx.store.list_agents()
        db_ok = True
    except Exception:
        db_ok = False
    response.status_code = 200 if db_ok else 503
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}


@router.get("/runs")
async def list_runs(
    ctx: ServerContext = Depends(get_context),
    limit: int | None = Query(None, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    from hive.logging.reader import LogReader

    reader = LogReader(ctx.root / "logs")
    # LogReader is fully synchronous (iterdir + read_text per run); run it off the
    # event loop so it can't stall the API (and the in-process daemon under
    # `serve --with-daemon`).
    runs = await asyncio.to_thread(reader.list_runs)
    if limit is not None:
        runs = runs[offset : offset + limit]
    return [r.model_dump(mode="json") for r in runs]


@router.get("/runs/{run_id}")
async def get_run(run_id: str, ctx: ServerContext = Depends(get_context)) -> dict[str, Any]:
    from hive.logging.reader import LogReader

    reader = LogReader(ctx.root / "logs")
    summary = await asyncio.to_thread(reader.get_summary, run_id)
    if not summary:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return summary
