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
async def get_run_trace(run_id: str, ctx: ServerContext = Depends(get_context)) -> dict[str, Any]:
    """Return the span-tree trace for a run."""
    from hive.logging.reader import LogReader
    from hive.logging.trace import TraceBuilder

    reader = LogReader(ctx.root / "logs")
    builder = TraceBuilder(reader)
    tree = await asyncio.to_thread(builder.build, run_id)
    if tree is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return tree.to_dict()


@router.get("/metrics", response_class=Response)
async def metrics(ctx: ServerContext = Depends(get_context)) -> Response:
    """Prometheus text-format metrics: agent statuses plus latest-run counters.

    Rendered by hand -- the exposition text format is trivial and not worth a
    dependency. The per-run values are snapshots of the most recent run's log
    summary, exposed as gauges (they reset when a new run starts, so they are
    deliberately NOT counters -- don't apply rate()/increase() to them).
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
    snapshot_help = {
        "goals_generated": "Goals generated in the latest run (snapshot; resets each run).",
        "goals_completed": "Goals completed in the latest run (snapshot; resets each run).",
        "goals_abandoned": "Goals abandoned in the latest run (snapshot; resets each run).",
        "tool_calls": "Tool calls in the latest run (snapshot; resets each run).",
        "total_tokens": "Tokens consumed in the latest run (snapshot; resets each run).",
        "total_cost_usd": "Estimated cost (USD) of the latest run (snapshot; resets each run).",
    }
    for key, help_text in snapshot_help.items():
        lines.append(f"# HELP hive_{key} {help_text}")
        lines.append(f"# TYPE hive_{key} gauge")
        lines.append(f"hive_{key} {summary.get(key, 0)}")
    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@router.post("/daemon/pause", status_code=200)
async def pause_daemon(ctx: ServerContext = Depends(get_context)) -> dict[str, str]:
    """Freeze the in-process daemon (ManualPauseGuard). Distinct from per-agent pause."""
    if ctx.daemon is None:
        raise HTTPException(status_code=503, detail="daemon not running")
    ctx.daemon.pause()
    return {"status": "paused"}


@router.post("/daemon/resume", status_code=200)
async def resume_daemon(ctx: ServerContext = Depends(get_context)) -> dict[str, str]:
    """Clear the daemon-wide pause."""
    if ctx.daemon is None:
        raise HTTPException(status_code=503, detail="daemon not running")
    ctx.daemon.resume()
    return {"status": "running"}


@router.get("/budget")
async def budget(ctx: ServerContext = Depends(get_context)) -> dict[str, Any]:
    """Return daemon-level budget status."""

    daemon = ctx.daemon
    if daemon is None:
        raise HTTPException(status_code=503, detail="daemon not running")
    s = daemon.budget.summary()
    unlimited = s.unlimited
    return {
        "budget_usd": s.budget_usd,
        "budget_tokens": s.budget_tokens,
        "spent_usd": round(s.spent_usd, 6),
        "spent_tokens": s.spent_tokens,
        "reserved_usd": round(s.reserved_usd, 6),
        "reserved_tokens": s.reserved_tokens,
        "remaining_usd": round(s.remaining_usd, 6) if s.remaining_usd != float("inf") else None,
        "remaining_tokens": s.remaining_tokens if s.remaining_tokens < 2**53 else None,
        "exceeded": s.exceeded,
        "unlimited": unlimited,
        "mode": s.mode,
        "status": "unlimited (budget_usd=0)" if unlimited else "limited",
    }


@router.post("/budget/reset")
async def budget_reset(ctx: ServerContext = Depends(get_context)) -> dict[str, str]:
    """Reset daemon budget spent counters."""

    daemon = ctx.daemon
    if daemon is None:
        raise HTTPException(status_code=503, detail="daemon not running")
    await daemon.reset_budget()
    return {"status": "reset"}


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``patch`` into ``base`` so nested siblings survive."""
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _redact_secrets(data: dict[str, Any]) -> dict[str, Any]:
    """Mask secret config values before returning them over HTTP."""
    server = data.get("server")
    if isinstance(server, dict) and server.get("api_key"):
        server["api_key"] = "***"
    return data


@router.get("/config")
async def get_config(ctx: ServerContext = Depends(get_context)) -> dict[str, Any]:
    """Return persisted, effective, and live config (secrets redacted)."""
    from hive.config import config_truth_views

    views = config_truth_views(ctx.hive_dir)
    return {
        "persisted": _redact_secrets(views["persisted"]),
        "effective": _redact_secrets(views["effective"]),
        "live": _redact_secrets(views["live"]) if views["live"] is not None else None,
        "restart_required_fields": views["restart_required_fields"],
    }


@router.patch("/config")
async def patch_config(
    body: dict[str, Any], ctx: ServerContext = Depends(get_context)
) -> dict[str, Any]:
    """Update config fields (partial update).

    Returns the merged config plus a ``reload`` map classifying each patched
    key as ``applied`` (hot-reloaded when the daemon is in-process) or
    ``restart_required``.
    """
    from hive.config import apply_config_patch

    try:
        data, reload_status = apply_config_patch(
            ctx.hive_dir,
            body,
            hot_reload=ctx.daemon.reload_config if ctx.daemon is not None else None,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid config: {e}") from e

    redacted = _redact_secrets(data)
    return {"config": redacted, "reload": reload_status}
