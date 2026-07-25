"""Trace tree — derive a span hierarchy from structured run logs.

Pure transform over JSONL data captured by :class:`LogWriter`.  The
underlying log files are never modified; ``TraceBuilder`` reads them via
:class:`LogReader` and assembles a tree of :class:`Span` objects that can
be serialised to JSON for the REST API or pretty-printed for the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from hive.logging.models import DecisionLog, GoalLog, ToolLog
from hive.logging.reader import LogReader


@dataclass
class Span:
    """A single node in the trace tree."""

    span_id: str
    parent_id: str | None
    name: str
    kind: str  # "run" | "cycle" | "agent" | "goal" | "decision" | "tool"
    start_time: str  # ISO-8601
    end_time: str | None = None
    status: str = "ok"  # "ok" | "error" | "timeout"
    attributes: dict[str, Any] = field(default_factory=dict)
    children: list[Span] = field(default_factory=list)

    def to_dict(self, *, include_children: bool = True) -> dict[str, Any]:
        d: dict[str, Any] = {
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "kind": self.kind,
            "start_time": self.start_time,
        }
        if self.end_time:
            d["end_time"] = self.end_time
        if self.status != "ok":
            d["status"] = self.status
        if self.attributes:
            d["attributes"] = self.attributes
        if include_children and self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d


@dataclass
class TraceTree:
    """A complete trace for one run."""

    run_id: str
    root: Span
    total_spans: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "total_spans": self.total_spans,
            "root": self.root.to_dict(),
        }


def _count_spans(span: Span) -> int:
    return 1 + sum(_count_spans(c) for c in span.children)


class TraceBuilder:
    """Build a trace tree from structured run logs."""

    def __init__(self, reader: LogReader):
        self._reader = reader

    def build(self, run_id: str) -> TraceTree | None:
        """Build a complete trace tree for the given run."""
        run = self._reader.get_run(run_id)
        if not run:
            return None

        root = Span(
            span_id=f"run-{run_id}",
            parent_id=None,
            name=f"Run {run_id}",
            kind="run",
            start_time=run.started_at.isoformat(),
            attributes={
                "heartbeat": run.heartbeat,
                "profiles": run.profiles,
                "agents_spawned": run.agents_spawned,
            },
        )

        cycles = self._reader.get_cycles(run_id)
        agent_ids = self._reader.get_agent_ids(run_id)

        for i, cycle_log in enumerate(cycles):
            # A goal belongs to the cycle whose time window contains its event,
            # so goals are attributed to one cycle instead of duplicated under
            # every cycle. The last cycle's window is open-ended.
            window_start = cycle_log.ts
            window_end = cycles[i + 1].ts if i + 1 < len(cycles) else None

            cycle_span = Span(
                span_id=f"cycle-{run_id}-{cycle_log.cycle}",
                parent_id=root.span_id,
                name=f"Cycle {cycle_log.cycle}",
                kind="cycle",
                start_time=cycle_log.ts.isoformat(),
                attributes={
                    "agents_active": cycle_log.agents_active,
                    "agents_in_crisis": cycle_log.agents_in_crisis,
                    "goals_completed": cycle_log.goals_completed_this_cycle,
                    "goals_abandoned": cycle_log.goals_abandoned_this_cycle,
                },
            )

            for agent_id in agent_ids:
                agent_span = self._build_agent_span(
                    run_id,
                    agent_id,
                    cycle_log.cycle,
                    cycle_span.span_id,
                    window_start,
                    window_end,
                )
                if agent_span.children:
                    cycle_span.children.append(agent_span)

            root.children.append(cycle_span)

        # Also attach any agent-level spans not tied to a specific cycle
        for agent_id in agent_ids:
            self._attach_orphan_goals(run_id, agent_id, root)

        return TraceTree(
            run_id=run_id,
            root=root,
            total_spans=_count_spans(root),
        )

    def _build_agent_span(
        self,
        run_id: str,
        agent_id: str,
        cycle: int,
        parent_id: str,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> Span:
        """Build agent-level sub-tree for one cycle.

        Only goals whose event timestamp falls in ``[window_start, window_end)``
        are attached, and each goal_id is rendered once (its latest event in the
        window), so a goal is never duplicated across cycles.
        """
        agent_span = Span(
            span_id=f"agent-{run_id}-{agent_id}-{cycle}",
            parent_id=parent_id,
            name=agent_id,
            kind="agent",
            start_time="",
            attributes={"cycle": cycle},
        )

        goals = self._reader.get_agent_goals(run_id, agent_id)
        decisions = self._reader.get_agent_decisions(run_id, agent_id)
        tools = self._reader.get_agent_tools(run_id, agent_id)

        # Keep only goal events in this cycle's time window, merged to one row
        # per goal_id: the latest (terminal) event wins for status/outcome, but
        # an objective from an earlier "set" event is preserved.
        in_window: dict[str, GoalLog] = {}
        for goal in goals:
            if window_start is not None and goal.ts < window_start:
                continue
            if window_end is not None and goal.ts >= window_end:
                continue
            prev = in_window.get(goal.goal_id)
            if prev is None:
                in_window[goal.goal_id] = goal
            else:
                merged = goal.model_copy()
                if not merged.objective and prev.objective:
                    merged.objective = prev.objective
                in_window[goal.goal_id] = merged
        windowed_goals = list(in_window.values())

        # Group decisions and tools by goal_id
        goal_map: dict[str, list[DecisionLog]] = {}
        for d in decisions:
            goal_map.setdefault(d.goal_id, []).append(d)

        tool_map: dict[str, list[ToolLog]] = {}
        for t in tools:
            tool_map.setdefault(t.goal_id, []).append(t)

        for goal in windowed_goals:
            goal_span = Span(
                span_id=f"goal-{goal.goal_id}",
                parent_id=agent_span.span_id,
                name=f"Goal: {goal.objective or goal.event}",
                kind="goal",
                start_time=goal.ts.isoformat(),
                status=(
                    "ok"
                    if goal.event == "completed"
                    else "error"
                    if goal.event == "abandoned"
                    else "ok"
                ),
                attributes={
                    "goal_id": goal.goal_id,
                    "event": goal.event,
                    "objective": goal.objective,
                    "outcome_summary": goal.outcome_summary,
                    "steps_done": goal.steps_done,
                    "steps_failed": goal.steps_failed,
                },
            )

            # Attach decisions under this goal
            for d in goal_map.get(goal.goal_id, []):
                decision_span = Span(
                    span_id=f"decision-{goal.goal_id}-{d.step_index}",
                    parent_id=goal_span.span_id,
                    name=f"Decision: {d.decision_type}",
                    kind="decision",
                    start_time=d.ts.isoformat(),
                    status="ok" if d.success else "error",
                    attributes={
                        "model": d.model,
                        "input_tokens": d.input_tokens,
                        "output_tokens": d.output_tokens,
                        "cost_usd": d.cost_usd,
                        "duration_ms": d.duration_ms,
                        "step_index": d.step_index,
                    },
                )

                # Attach tool calls under the matching decision (by step_index)
                for t in tool_map.get(goal.goal_id, []):
                    if t.step_index == d.step_index:
                        tool_span = Span(
                            span_id=f"tool-{goal.goal_id}-{t.step_index}-{t.tool_name}",
                            parent_id=decision_span.span_id,
                            name=f"Tool: {t.tool_name}",
                            kind="tool",
                            start_time=t.ts.isoformat(),
                            status="ok" if t.success else "error",
                            attributes={
                                "tool_name": t.tool_name,
                                "params": t.params_raw,
                                "output": t.output[:500] if t.output else "",
                                "error": t.error,
                                "duration_ms": t.duration_ms,
                            },
                        )
                        decision_span.children.append(tool_span)

                goal_span.children.append(decision_span)

            if goal_span.children:
                agent_span.children.append(goal_span)

        return agent_span

    def _attach_orphan_goals(self, run_id: str, agent_id: str, root: Span) -> None:
        """Attach goals that don't match any cycle directly under root."""
        goals = self._reader.get_agent_goals(run_id, agent_id)
        existing_goal_ids = set()
        for cycle_span in root.children:
            for agent_span in cycle_span.children:
                for goal_span in agent_span.children:
                    existing_goal_ids.add(goal_span.attributes.get("goal_id", ""))

        for goal in goals:
            if goal.goal_id not in existing_goal_ids and goal.goal_id:
                orphan = Span(
                    span_id=f"goal-{goal.goal_id}",
                    parent_id=root.span_id,
                    name=f"Goal: {goal.objective or goal.event}",
                    kind="goal",
                    start_time=goal.ts.isoformat(),
                    attributes={
                        "goal_id": goal.goal_id,
                        "agent_id": agent_id,
                        "event": goal.event,
                        "objective": goal.objective,
                    },
                )
                root.children.append(orphan)


def format_span_tree(span: Span, indent: int = 0) -> str:
    """Render a span tree as human-readable text."""
    prefix = "  " * indent
    connector = "├── " if indent > 0 else ""
    status_marker = ""
    if span.status == "error":
        status_marker = " ✗"
    elif span.status == "timeout":
        status_marker = " ⏱"

    line = f"{prefix}{connector}[{span.kind}] {span.name}{status_marker}"

    # Add key attributes
    extras = []
    if span.kind == "decision":
        if span.attributes.get("model"):
            extras.append(f"model={span.attributes['model']}")
        if span.attributes.get("input_tokens"):
            extras.append(
                f"tokens={span.attributes['input_tokens']}"
                f"+{span.attributes.get('output_tokens', 0)}"
            )
        if span.attributes.get("cost_usd"):
            extras.append(f"cost=${span.attributes['cost_usd']:.4f}")
    elif span.kind == "tool":
        if span.attributes.get("duration_ms"):
            extras.append(f"{span.attributes['duration_ms']}ms")
    elif span.kind == "cycle":
        if span.attributes.get("agents_active"):
            extras.append(f"agents={span.attributes['agents_active']}")

    if extras:
        line += f" ({', '.join(extras)})"

    lines = [line]
    for child in span.children:
        lines.append(format_span_tree(child, indent + 1))
    return "\n".join(lines)
