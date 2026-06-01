"""Round-trip tests for the structured log writer/reader (F1 coverage)."""

from __future__ import annotations

import threading
from pathlib import Path

from hive.logging.models import (
    CycleLog,
    DecisionLog,
    GoalLog,
    SufferingLog,
    ToolLog,
)
from hive.logging.reader import LogReader
from hive.logging.writer import LogWriter


def _start_run(writer: LogWriter) -> str:
    return writer.start_run(
        heartbeat=10,
        profiles=["coder"],
        agents=["a1"],
        tools=["world_query"],
    )


class TestWriterReaderRoundTrip:
    def test_start_run_creates_layout_and_run_json(self, tmp_path: Path) -> None:
        writer = LogWriter(tmp_path)
        run_id = _start_run(writer)

        run_dir = tmp_path / "runs" / run_id
        assert (run_dir / "run.json").exists()
        assert (run_dir / "cycles").is_dir()
        assert (run_dir / "agents").is_dir()

        reader = LogReader(tmp_path)
        run = reader.get_run(run_id)
        assert run is not None
        assert run.heartbeat == 10
        assert run.profiles == ["coder"]
        assert run.agents_spawned == ["a1"]

    def test_all_record_types_round_trip(self, tmp_path: Path) -> None:
        writer = LogWriter(tmp_path)
        run_id = _start_run(writer)

        writer.log_cycle(CycleLog(run_id=run_id, cycle=1, agents_active=1))
        writer.log_goal(GoalLog(agent_id="a1", goal_id="g1", event="generated", objective="ship"))
        writer.log_goal(GoalLog(agent_id="a1", goal_id="g1", event="completed", steps_done=3))
        writer.log_decision(
            DecisionLog(agent_id="a1", decision_type="goal", input_tokens=10, output_tokens=5)
        )
        writer.log_tool(ToolLog(agent_id="a1", tool_name="world_query", success=True))
        writer.log_suffering(SufferingLog(agent_id="a1", cycle=1, cumulative_load=0.2))

        reader = LogReader(tmp_path)
        cycles = reader.get_cycles(run_id)
        assert len(cycles) == 1 and cycles[0].agents_active == 1

        goals = reader.get_agent_goals(run_id, "a1")
        assert {g.event for g in goals} == {"generated", "completed"}

        decisions = reader.get_agent_decisions(run_id, "a1")
        assert len(decisions) == 1 and decisions[0].input_tokens == 10

        tools = reader.get_agent_tools(run_id, "a1")
        assert len(tools) == 1 and tools[0].tool_name == "world_query"

        suffering = reader.get_agent_suffering(run_id, "a1")
        assert len(suffering) == 1 and suffering[0].cumulative_load == 0.2

        assert reader.get_agent_ids(run_id) == ["a1"]

    def test_get_summary_aggregates(self, tmp_path: Path) -> None:
        writer = LogWriter(tmp_path)
        run_id = _start_run(writer)

        writer.log_goal(GoalLog(agent_id="a1", goal_id="g1", event="generated"))
        writer.log_goal(GoalLog(agent_id="a1", goal_id="g1", event="completed"))
        writer.log_goal(GoalLog(agent_id="a1", goal_id="g2", event="generated"))
        writer.log_goal(GoalLog(agent_id="a1", goal_id="g2", event="abandoned"))
        writer.log_tool(ToolLog(agent_id="a1", tool_name="t", success=True))
        writer.log_decision(
            DecisionLog(
                agent_id="a1",
                decision_type="goal",
                input_tokens=100,
                output_tokens=50,
                cost_usd=0.01,
            )
        )

        summary = LogReader(tmp_path).get_summary(run_id)
        assert summary["agents"] == 1
        assert summary["goals_generated"] == 2
        assert summary["goals_completed"] == 1
        assert summary["goals_abandoned"] == 1
        assert summary["tool_calls"] == 1
        assert summary["total_tokens"] == 150
        assert summary["total_cost_usd"] == 0.01


class TestReaderMissingData:
    def test_list_runs_empty_when_no_dir(self, tmp_path: Path) -> None:
        assert LogReader(tmp_path).list_runs() == []

    def test_get_missing_run_returns_none(self, tmp_path: Path) -> None:
        LogWriter(tmp_path)  # creates runs/ dir but no run
        assert LogReader(tmp_path).get_run("run-does-not-exist") is None

    def test_summary_of_missing_run_is_empty(self, tmp_path: Path) -> None:
        assert LogReader(tmp_path).get_summary("nope") == {}

    def test_queries_on_missing_run_return_empty_lists(self, tmp_path: Path) -> None:
        reader = LogReader(tmp_path)
        assert reader.get_cycles("nope") == []
        assert reader.get_agent_goals("nope", "a1") == []
        assert reader.get_agent_ids("nope") == []

    def test_list_runs_after_start(self, tmp_path: Path) -> None:
        writer = LogWriter(tmp_path)
        run_id = _start_run(writer)
        runs = LogReader(tmp_path).list_runs()
        assert [r.run_id for r in runs] == [run_id]


class TestConcurrentWrites:
    def test_concurrent_tool_logs_all_land(self, tmp_path: Path) -> None:
        """The threading.Lock in the writer keeps concurrent appends intact."""
        writer = LogWriter(tmp_path)
        run_id = _start_run(writer)

        def write(i: int) -> None:
            writer.log_tool(ToolLog(agent_id="a1", tool_name=f"tool-{i}", success=True))

        threads = [threading.Thread(target=write, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        tools = LogReader(tmp_path).get_agent_tools(run_id, "a1")
        assert len(tools) == 50
        assert {t.tool_name for t in tools} == {f"tool-{i}" for i in range(50)}
