"""Trace tree derived from a run's structured JSONL logs.

A pure data transform: ``TraceBuilder`` reads a finished (or in-progress) run
via ``LogReader`` and derives a span tree -- run -> agent -> goal ->
decision/tool -- from the correlation fields (``goal_id``, ``step_index``)
the writers already record. The JSONL files stay the single source of truth;
no new write path is introduced.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from hive.logging.reader import LogReader

SpanKind = Literal["run", "agent", "goal", "decision", "tool"]


def _seg(value: str) -> str:
    """Sanitize one span-id path segment.

    Span ids join segments with ``/``; a literal ``/`` inside an agent or
    goal id would let two distinct tuples collide on the same span id.
    """
    return value.replace("/", "%2F")


class Span(BaseModel):
    """One node in the derived trace tree.

    ``span_id`` values are deterministic paths (``run/agent/goal/...``) so the
    same logs always produce the same tree.
    """

    span_id: str
    parent_span_id: str | None = None
    name: str
    kind: SpanKind
    start: datetime | None = None
    end: datetime | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class TraceBuilder:
    """Builds span trees from run logs."""

    def __init__(self, logs_dir: Path):
        self._reader = LogReader(logs_dir)

    def build(self, run_id: str) -> list[Span]:
        """Derive the span tree for ``run_id``.

        Returns an empty list for an unknown run. Decisions/tools whose
        ``goal_id`` matches no goal span (e.g. goal-generation decisions, or
        logs from before correlation fields existed) attach to the agent span
        rather than being dropped.
        """
        run = self._reader.get_run(run_id)
        if run is None:
            return []

        run_span = Span(
            span_id=run_id,
            name=f"run {run_id}",
            kind="run",
            start=run.started_at,
            attributes={"heartbeat": run.heartbeat, "profiles": run.profiles},
        )
        spans = [run_span]

        for agent_id in self._reader.get_agent_ids(run_id):
            agent_span_id = f"{run_id}/{_seg(agent_id)}"
            spans.append(
                Span(
                    span_id=agent_span_id,
                    parent_span_id=run_id,
                    name=agent_id,
                    kind="agent",
                )
            )

            goal_spans: dict[str, Span] = {}
            for goal in self._reader.get_agent_goals(run_id, agent_id):
                existing = goal_spans.get(goal.goal_id)
                if existing is None:
                    span = Span(
                        span_id=f"{agent_span_id}/{_seg(goal.goal_id)}",
                        parent_span_id=agent_span_id,
                        name=goal.objective or goal.goal_id,
                        kind="goal",
                        start=goal.ts if goal.event == "generated" else None,
                        attributes={
                            "goal_id": goal.goal_id,
                            # "in_progress" until a terminal event closes the
                            # span, so a crashed or mid-flight run is
                            # distinguishable from a closed goal.
                            "outcome": ("in_progress" if goal.event == "generated" else goal.event),
                        },
                    )
                    goal_spans[goal.goal_id] = span
                    spans.append(span)
                else:
                    # Later events (completed/abandoned) close and annotate the span.
                    existing.attributes["outcome"] = goal.event
                    if goal.event in ("completed", "abandoned"):
                        existing.end = goal.ts
                    if goal.objective and existing.name == goal.goal_id:
                        existing.name = goal.objective
            goal_span_ids = {gid: s.span_id for gid, s in goal_spans.items()}

            for i, d in enumerate(self._reader.get_agent_decisions(run_id, agent_id)):
                parent = goal_span_ids.get(d.goal_id, agent_span_id)
                spans.append(
                    Span(
                        span_id=f"{parent}/d{i}",
                        parent_span_id=parent,
                        name=f"{d.decision_type} #{d.step_index or i}",
                        kind="decision",
                        start=d.ts,
                        attributes={
                            "model": d.model,
                            "input_tokens": d.input_tokens,
                            "output_tokens": d.output_tokens,
                            "cost_usd": d.cost_usd,
                            "duration_ms": d.duration_ms,
                            "success": d.success,
                        },
                    )
                )

            for i, t in enumerate(self._reader.get_agent_tools(run_id, agent_id)):
                parent = goal_span_ids.get(t.goal_id, agent_span_id)
                spans.append(
                    Span(
                        span_id=f"{parent}/t{i}",
                        parent_span_id=parent,
                        name=t.tool_name,
                        kind="tool",
                        start=t.ts,
                        attributes={
                            "step_index": t.step_index,
                            "success": t.success,
                            "duration_ms": t.duration_ms,
                            "error": t.error,
                        },
                    )
                )

        return spans


def children_of(spans: list[Span], parent_id: str | None) -> list[Span]:
    """Direct children of ``parent_id`` (None = roots), in log order."""
    return [s for s in spans if s.parent_span_id == parent_id]
