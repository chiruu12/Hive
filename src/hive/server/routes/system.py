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


@router.get("/runs/{run_id}/trace")
async def get_run_trace(
    run_id: str, ctx: ServerContext = Depends(get_context)
) -> list[dict[str, Any]]:
    """Span tree (run -> agent -> goal -> decision/tool) derived from run logs."""
    from hive.logging.trace import TraceBuilder

    builder = TraceBuilder(ctx.root / "logs")
    spans = await asyncio.to_thread(builder.build, run_id)
    if not spans:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return [s.model_dump(mode="json") for s in spans]


@router.get("/metrics", response_class=Response)
async def metrics(ctx: ServerContext = Depends(get_context)) -> Response:
    """Prometheus text-format metrics: agent statuses plus latest-run counters.

    Rendered by hand -- the exposition text format is trivial and not worth a
    dependency. Counters come from the most recent run's log summary.
    """
    from hive.logging.reader import LogReader

    agents = await ctx.store.list_agents()
    by_status: dict[str, int] = {}
    for a in agents:
        by_status[a.status.value] = by_status.get(a.status.value, 0) + 1

    reader = LogReader(ctx.root / "logs")
    runs = await asyncio.to_thread(reader.list_runs)
    summary: dict[str, Any] = {}
    if runs:
        summary = await asyncio.to_thread(reader.get_summary, runs[0].run_id)

    lines = [
        "# HELP hive_agents Agents known to the store, by status.",
        "# TYPE hive_agents gauge",
    ]
    for status_value, count in sorted(by_status.items()):
        lines.append(f'hive_agents{{status="{status_value}"}} {count}')
    counter_help = {
        "goals_generated": "Goals generated in the latest run.",
        "goals_completed": "Goals completed in the latest run.",
        "goals_abandoned": "Goals abandoned in the latest run.",
        "tool_calls": "Tool calls in the latest run.",
        "total_tokens": "Tokens consumed in the latest run.",
        "total_cost_usd": "Estimated cost (USD) of the latest run.",
    }
    for key, help_text in counter_help.items():
        lines.append(f"# HELP hive_{key} {help_text}")
        lines.append(f"# TYPE hive_{key} gauge")
        lines.append(f"hive_{key} {summary.get(key, 0)}")
    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
