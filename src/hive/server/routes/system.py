"""System endpoints: status, health, and run-log listing."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from hive.server.deps import ServerContext, get_context

router = APIRouter(tags=["system"])


@router.get("/status")
async def status(ctx: ServerContext = Depends(get_context)) -> list[dict[str, Any]]:
    """Status of all agents (mirrors ``hive status``)."""
    agents = await ctx.store.list_agents()
    out: list[dict[str, Any]] = []
    for a in agents:
        goal = await ctx.store.get_active_goal(a.agent_id)
        out.append(
            {
                "agent_id": a.agent_id,
                "name": a.name,
                "role": a.role,
                "model": a.model,
                "status": a.status.value,
                "goal": goal["objective"] if goal else None,
            }
        )
    return out


@router.get("/healthz")
async def healthz(ctx: ServerContext = Depends(get_context)) -> dict[str, Any]:
    """Liveness + readiness (DB reachable)."""
    try:
        await ctx.store.list_agents()
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}


@router.get("/runs")
async def list_runs(ctx: ServerContext = Depends(get_context)) -> list[dict[str, Any]]:
    from hive.logging.reader import LogReader

    reader = LogReader(ctx.root / "logs")
    return [r.model_dump(mode="json") for r in reader.list_runs()]


@router.get("/runs/{run_id}")
async def get_run(run_id: str, ctx: ServerContext = Depends(get_context)) -> dict[str, Any] | None:
    from hive.logging.reader import LogReader

    reader = LogReader(ctx.root / "logs")
    return reader.get_summary(run_id)
