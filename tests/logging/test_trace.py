"""Tests for the derived span tree (TraceBuilder)."""

from __future__ import annotations

from pathlib import Path

from hive.logging.models import DecisionLog, GoalLog, ToolLog
from hive.logging.trace import TraceBuilder, children_of
from hive.logging.writer import LogWriter


def _write_fixture_run(logs_dir: Path) -> str:
    """One agent, one goal with a decision + tool, plus an uncorrelated decision."""
    writer = LogWriter(logs_dir)
    writer.start_run(heartbeat=5, profiles=["coder"], agents=["coder-1"], tools=["file_read"])
    writer.log_goal(
        GoalLog(agent_id="coder-1", goal_id="goal-aaa", event="generated", objective="write docs")
    )
    writer.log_decision(
        DecisionLog(
            agent_id="coder-1",
            goal_id="goal-aaa",
            step_index=1,
            decision_type="react_step",
            model="mock",
            input_tokens=10,
            output_tokens=5,
        )
    )
    writer.log_tool(
        ToolLog(
            agent_id="coder-1",
            goal_id="goal-aaa",
            step_index=1,
            tool_name="file_read",
            success=True,
        )
    )
    # Goal-generation decision: no goal_id -> should attach to the agent span.
    writer.log_decision(
        DecisionLog(agent_id="coder-1", decision_type="goal_generation", model="mock")
    )
    writer.log_goal(GoalLog(agent_id="coder-1", goal_id="goal-aaa", event="completed"))
    return writer.run_id


class TestTraceBuilder:
    def test_unknown_run_returns_empty(self, tmp_path: Path) -> None:
        assert TraceBuilder(tmp_path).build("nope") == []

    def test_tree_shape(self, tmp_path: Path) -> None:
        run_id = _write_fixture_run(tmp_path)
        spans = TraceBuilder(tmp_path).build(run_id)

        root = spans[0]
        assert root.kind == "run" and root.span_id == run_id

        agents = children_of(spans, run_id)
        assert [a.kind for a in agents] == ["agent"]
        agent = agents[0]

        agent_children = children_of(spans, agent.span_id)
        kinds = sorted(c.kind for c in agent_children)
        # The goal span plus the uncorrelated goal-generation decision.
        assert kinds == ["decision", "goal"]

        goal = next(c for c in agent_children if c.kind == "goal")
        assert goal.name == "write docs"
        assert goal.attributes["outcome"] == "completed"
        assert goal.start is not None and goal.end is not None

        goal_children = children_of(spans, goal.span_id)
        assert sorted(c.kind for c in goal_children) == ["decision", "tool"]
        tool = next(c for c in goal_children if c.kind == "tool")
        assert tool.name == "file_read" and tool.attributes["success"] is True

    def test_span_ids_deterministic(self, tmp_path: Path) -> None:
        run_id = _write_fixture_run(tmp_path)
        first = [s.span_id for s in TraceBuilder(tmp_path).build(run_id)]
        second = [s.span_id for s in TraceBuilder(tmp_path).build(run_id)]
        assert first == second

    def test_open_goal_reports_in_progress(self, tmp_path: Path) -> None:
        """A goal with no terminal event (crash / mid-flight snapshot) must not
        read as 'generated' -- it shows 'in_progress' and stays unclosed."""
        writer = LogWriter(tmp_path)
        writer.start_run(heartbeat=5, profiles=[], agents=["a-1"], tools=[])
        writer.log_goal(
            GoalLog(agent_id="a-1", goal_id="goal-open", event="generated", objective="ongoing")
        )

        spans = TraceBuilder(tmp_path).build(writer.run_id)
        goal = next(s for s in spans if s.kind == "goal")
        assert goal.attributes["outcome"] == "in_progress"
        assert goal.end is None

    def test_slash_in_goal_id_does_not_collide(self, tmp_path: Path) -> None:
        """A '/' inside a goal_id is sanitized, so a goal literally named
        'g/d0' can't collide with goal 'g's first decision span ('.../g/d0')."""
        writer = LogWriter(tmp_path)
        writer.start_run(heartbeat=5, profiles=[], agents=["a-1"], tools=[])
        writer.log_goal(GoalLog(agent_id="a-1", goal_id="g", event="generated"))
        writer.log_decision(
            DecisionLog(agent_id="a-1", goal_id="g", step_index=1, decision_type="react_step")
        )
        writer.log_goal(GoalLog(agent_id="a-1", goal_id="g/d0", event="generated"))

        spans = TraceBuilder(tmp_path).build(writer.run_id)
        ids = [s.span_id for s in spans]
        assert len(ids) == len(set(ids)), "span ids must be unique"
        assert len([s for s in spans if s.kind == "goal"]) == 2

    def test_old_logs_without_correlation_still_build(self, tmp_path: Path) -> None:
        """Pre-correlation logs (no goal_id) attach to the agent span, not dropped."""
        writer = LogWriter(tmp_path)
        writer.start_run(heartbeat=5, profiles=[], agents=["old-1"], tools=[])
        writer.log_decision(DecisionLog(agent_id="old-1", decision_type="react_step"))
        writer.log_tool(ToolLog(agent_id="old-1", tool_name="shell_exec", success=False))

        spans = TraceBuilder(tmp_path).build(writer.run_id)
        agent = next(s for s in spans if s.kind == "agent")
        kinds = sorted(c.kind for c in children_of(spans, agent.span_id))
        assert kinds == ["decision", "tool"]
