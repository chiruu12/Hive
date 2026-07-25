"""Tests for the trace tree builder."""

from __future__ import annotations

from pathlib import Path

from hive.logging.models import (
    CycleLog,
    DecisionLog,
    GoalLog,
    ToolLog,
)
from hive.logging.reader import LogReader
from hive.logging.trace import (
    Span,
    TraceBuilder,
    TraceTree,
    format_span_tree,
)
from hive.logging.writer import LogWriter


def _write_test_run(writer: LogWriter) -> str:
    """Write a realistic test run with cycles, goals, decisions, and tools."""
    run_id = writer.start_run(
        heartbeat=10,
        profiles=["coder"],
        agents=["alice", "bob"],
        tools=["file_read", "shell_exec"],
    )

    # Cycle 0
    writer.log_cycle(CycleLog(run_id=run_id, cycle=0, agents_active=2))

    # Alice's goal
    writer.log_goal(
        GoalLog(
            agent_id="alice",
            goal_id="g-alice-1",
            event="generated",
            objective="Write tests",
        )
    )
    writer.log_decision(
        DecisionLog(
            agent_id="alice",
            goal_id="g-alice-1",
            step_index=0,
            decision_type="pursue",
            model="claude-haiku-4-5",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
            duration_ms=500,
        )
    )
    writer.log_tool(
        ToolLog(
            agent_id="alice",
            goal_id="g-alice-1",
            step_index=0,
            tool_name="file_read",
            success=True,
            output="file contents",
            duration_ms=50,
        )
    )
    writer.log_tool(
        ToolLog(
            agent_id="alice",
            goal_id="g-alice-1",
            step_index=0,
            tool_name="shell_exec",
            success=False,
            error="command not found",
            duration_ms=100,
        )
    )
    writer.log_decision(
        DecisionLog(
            agent_id="alice",
            goal_id="g-alice-1",
            step_index=1,
            decision_type="complete",
            model="claude-haiku-4-5",
            input_tokens=200,
            output_tokens=80,
            cost_usd=0.002,
            duration_ms=300,
        )
    )
    writer.log_goal(
        GoalLog(
            agent_id="alice",
            goal_id="g-alice-1",
            event="completed",
            steps_done=2,
            outcome_summary="Tests written successfully",
        )
    )

    # Bob's goal
    writer.log_goal(
        GoalLog(
            agent_id="bob",
            goal_id="g-bob-1",
            event="generated",
            objective="Review code",
        )
    )
    writer.log_decision(
        DecisionLog(
            agent_id="bob",
            goal_id="g-bob-1",
            step_index=0,
            decision_type="pursue",
            model="gpt-4o-mini",
            input_tokens=80,
            output_tokens=40,
            cost_usd=0.0005,
            duration_ms=400,
        )
    )
    writer.log_goal(
        GoalLog(
            agent_id="bob",
            goal_id="g-bob-1",
            event="abandoned",
            steps_failed=1,
            outcome_summary="Timed out",
        )
    )

    # Cycle 1
    writer.log_cycle(
        CycleLog(run_id=run_id, cycle=1, agents_active=2, goals_completed_this_cycle=1)
    )

    return run_id


class TestTraceBuilder:
    def test_build_returns_none_for_missing_run(self, tmp_path: Path):
        reader = LogReader(tmp_path)
        builder = TraceBuilder(reader)
        assert builder.build("nonexistent") is None

    def test_build_creates_tree(self, tmp_path: Path):
        writer = LogWriter(tmp_path)
        run_id = _write_test_run(writer)

        reader = LogReader(tmp_path)
        builder = TraceBuilder(reader)
        tree = builder.build(run_id)

        assert tree is not None
        assert isinstance(tree, TraceTree)
        assert tree.run_id == run_id
        assert tree.root.kind == "run"
        assert tree.total_spans > 0

    def test_tree_has_cycle_spans(self, tmp_path: Path):
        writer = LogWriter(tmp_path)
        run_id = _write_test_run(writer)

        reader = LogReader(tmp_path)
        tree = TraceBuilder(reader).build(run_id)

        cycle_spans = [c for c in tree.root.children if c.kind == "cycle"]
        assert len(cycle_spans) == 2
        assert cycle_spans[0].name == "Cycle 0"
        assert cycle_spans[1].name == "Cycle 1"

    def test_tree_has_agent_spans(self, tmp_path: Path):
        writer = LogWriter(tmp_path)
        run_id = _write_test_run(writer)

        reader = LogReader(tmp_path)
        tree = TraceBuilder(reader).build(run_id)

        cycle_0 = tree.root.children[0]
        agent_names = {c.name for c in cycle_0.children}
        assert "alice" in agent_names
        assert "bob" in agent_names

    def test_tree_has_goal_spans(self, tmp_path: Path):
        writer = LogWriter(tmp_path)
        run_id = _write_test_run(writer)

        reader = LogReader(tmp_path)
        tree = TraceBuilder(reader).build(run_id)

        # Find alice's span (order depends on filesystem)
        cycle_0 = tree.root.children[0]
        alice_span = next(c for c in cycle_0.children if c.name == "alice")
        goal_spans = [c for c in alice_span.children if c.kind == "goal"]
        assert len(goal_spans) >= 1
        assert "Write tests" in goal_spans[0].name

    def test_goal_not_duplicated_across_cycles(self, tmp_path: Path):
        # A goal must be attributed to exactly one cycle, not attached under
        # every cycle span (which inflated total_spans and reused span_ids).
        writer = LogWriter(tmp_path)
        run_id = _write_test_run(writer)

        reader = LogReader(tmp_path)
        tree = TraceBuilder(reader).build(run_id)

        def _count(span: object, span_id: str) -> int:
            n = 1 if getattr(span, "span_id", None) == span_id else 0
            for child in getattr(span, "children", []):
                n += _count(child, span_id)
            return n

        assert _count(tree.root, "goal-g-alice-1") == 1
        assert _count(tree.root, "goal-g-bob-1") == 1

    def test_tree_has_decision_spans(self, tmp_path: Path):
        writer = LogWriter(tmp_path)
        run_id = _write_test_run(writer)

        reader = LogReader(tmp_path)
        tree = TraceBuilder(reader).build(run_id)

        cycle_0 = tree.root.children[0]
        alice_span = next(c for c in cycle_0.children if c.name == "alice")
        goal_span = alice_span.children[0]
        decision_spans = [c for c in goal_span.children if c.kind == "decision"]
        assert len(decision_spans) == 2

    def test_tree_has_tool_spans(self, tmp_path: Path):
        writer = LogWriter(tmp_path)
        run_id = _write_test_run(writer)

        reader = LogReader(tmp_path)
        tree = TraceBuilder(reader).build(run_id)

        cycle_0 = tree.root.children[0]
        alice_span = next(c for c in cycle_0.children if c.name == "alice")
        goal_span = alice_span.children[0]
        decision_span = goal_span.children[0]
        tool_spans = [c for c in decision_span.children if c.kind == "tool"]
        assert len(tool_spans) == 2
        assert tool_spans[0].name == "Tool: file_read"
        assert tool_spans[0].status == "ok"
        assert tool_spans[1].name == "Tool: shell_exec"
        assert tool_spans[1].status == "error"

    def test_span_attributes(self, tmp_path: Path):
        writer = LogWriter(tmp_path)
        run_id = _write_test_run(writer)

        reader = LogReader(tmp_path)
        tree = TraceBuilder(reader).build(run_id)

        cycle_0 = tree.root.children[0]
        alice_span = next(c for c in cycle_0.children if c.name == "alice")
        goal_span = alice_span.children[0]
        decision = goal_span.children[0]
        assert decision.attributes["model"] == "claude-haiku-4-5"
        assert decision.attributes["input_tokens"] == 100
        assert decision.attributes["cost_usd"] == 0.001

    def test_goal_status_reflects_event(self, tmp_path: Path):
        writer = LogWriter(tmp_path)
        run_id = _write_test_run(writer)

        reader = LogReader(tmp_path)
        tree = TraceBuilder(reader).build(run_id)

        # Find all goal spans across the tree
        all_goals = []
        for cycle in tree.root.children:
            for agent in cycle.children:
                for goal in agent.children:
                    all_goals.append(goal)

        # Bob's abandoned goal should have error status
        abandoned = [
            g for g in all_goals if g.attributes.get("goal_id") == "g-bob-1" and g.status == "error"
        ]
        assert len(abandoned) >= 1

    def test_to_dict_serializable(self, tmp_path: Path):
        writer = LogWriter(tmp_path)
        run_id = _write_test_run(writer)

        reader = LogReader(tmp_path)
        tree = TraceBuilder(reader).build(run_id)

        d = tree.to_dict()
        assert d["run_id"] == run_id
        assert "root" in d
        assert "total_spans" in d
        # Should be JSON-serializable
        import json

        json.dumps(d)

    def test_empty_run(self, tmp_path: Path):
        writer = LogWriter(tmp_path)
        run_id = writer.start_run(heartbeat=10, profiles=["p"], agents=["a"], tools=[])

        reader = LogReader(tmp_path)
        tree = TraceBuilder(reader).build(run_id)

        assert tree is not None
        assert tree.root.kind == "run"
        assert tree.root.children == []

    def test_total_spans_count(self, tmp_path: Path):
        writer = LogWriter(tmp_path)
        run_id = _write_test_run(writer)

        reader = LogReader(tmp_path)
        tree = TraceBuilder(reader).build(run_id)

        # Should count: 1 run + 2 cycles + agents + goals + decisions + tools
        assert tree.total_spans > 10


class TestFormatSpanTree:
    def test_format_basic(self, tmp_path: Path):
        writer = LogWriter(tmp_path)
        run_id = _write_test_run(writer)

        reader = LogReader(tmp_path)
        tree = TraceBuilder(reader).build(run_id)

        text = format_span_tree(tree.root)
        assert "[run]" in text
        assert "[cycle]" in text
        assert "[agent]" in text
        assert "[goal]" in text
        assert "[decision]" in text
        assert "[tool]" in text

    def test_format_shows_error_status(self, tmp_path: Path):
        writer = LogWriter(tmp_path)
        run_id = _write_test_run(writer)

        reader = LogReader(tmp_path)
        tree = TraceBuilder(reader).build(run_id)

        text = format_span_tree(tree.root)
        assert "✗" in text  # error marker

    def test_format_shows_attributes(self, tmp_path: Path):
        writer = LogWriter(tmp_path)
        run_id = _write_test_run(writer)

        reader = LogReader(tmp_path)
        tree = TraceBuilder(reader).build(run_id)

        text = format_span_tree(tree.root)
        assert "model=" in text
        assert "tokens=" in text

    def test_format_single_span(self):
        span = Span(
            span_id="test",
            parent_id=None,
            name="Test",
            kind="run",
            start_time="2025-01-01T00:00:00",
        )
        text = format_span_tree(span)
        assert "[run] Test" in text


class TestSpanToDict:
    def test_basic_dict(self):
        span = Span(
            span_id="s1",
            parent_id=None,
            name="Test",
            kind="run",
            start_time="2025-01-01T00:00:00",
            end_time="2025-01-01T00:01:00",
            attributes={"key": "value"},
        )
        d = span.to_dict()
        assert d["span_id"] == "s1"
        assert d["name"] == "Test"
        assert d["kind"] == "run"
        assert d["end_time"] == "2025-01-01T00:01:00"
        assert d["attributes"] == {"key": "value"}
        assert "status" not in d  # default "ok" not serialized

    def test_error_status_serialized(self):
        span = Span(
            span_id="s1",
            parent_id=None,
            name="Fail",
            kind="tool",
            start_time="2025-01-01T00:00:00",
            status="error",
        )
        d = span.to_dict()
        assert d["status"] == "error"

    def test_children_included(self):
        child = Span(
            span_id="c1",
            parent_id="s1",
            name="Child",
            kind="tool",
            start_time="2025-01-01T00:00:00",
        )
        parent = Span(
            span_id="s1",
            parent_id=None,
            name="Parent",
            kind="run",
            start_time="2025-01-01T00:00:00",
            children=[child],
        )
        d = parent.to_dict()
        assert len(d["children"]) == 1
        assert d["children"][0]["name"] == "Child"

    def test_children_excluded(self):
        child = Span(
            span_id="c1",
            parent_id="s1",
            name="Child",
            kind="tool",
            start_time="2025-01-01T00:00:00",
        )
        parent = Span(
            span_id="s1",
            parent_id=None,
            name="Parent",
            kind="run",
            start_time="2025-01-01T00:00:00",
            children=[child],
        )
        d = parent.to_dict(include_children=False)
        assert "children" not in d
