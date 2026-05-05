"""Structured log reader — load and analyze past runs."""

from pathlib import Path

from hive.logging.models import (
    CycleLog,
    DecisionLog,
    GoalLog,
    RunLog,
    SufferingLog,
    ToolLog,
)


class LogReader:
    """Reads structured logs from past runs for analysis."""

    def __init__(self, logs_dir: Path):
        self._runs_dir = logs_dir / "runs"

    def list_runs(self) -> list[RunLog]:
        if not self._runs_dir.exists():
            return []
        runs = []
        for d in sorted(self._runs_dir.iterdir(), reverse=True):
            run_file = d / "run.json"
            if run_file.exists():
                runs.append(RunLog.model_validate_json(run_file.read_text()))
        return runs

    def get_run(self, run_id: str) -> RunLog | None:
        run_file = self._runs_dir / run_id / "run.json"
        if not run_file.exists():
            return None
        return RunLog.model_validate_json(run_file.read_text())

    def get_cycles(self, run_id: str) -> list[CycleLog]:
        return self._read_jsonl(self._runs_dir / run_id / "cycles", "cycle_*.jsonl", CycleLog)

    def get_agent_goals(self, run_id: str, agent_id: str) -> list[GoalLog]:
        path = self._runs_dir / run_id / "agents" / agent_id / "goals.jsonl"
        return self._read_file(path, GoalLog)

    def get_agent_decisions(self, run_id: str, agent_id: str) -> list[DecisionLog]:
        path = self._runs_dir / run_id / "agents" / agent_id / "decisions.jsonl"
        return self._read_file(path, DecisionLog)

    def get_agent_tools(self, run_id: str, agent_id: str) -> list[ToolLog]:
        path = self._runs_dir / run_id / "agents" / agent_id / "tools.jsonl"
        return self._read_file(path, ToolLog)

    def get_agent_suffering(self, run_id: str, agent_id: str) -> list[SufferingLog]:
        path = self._runs_dir / run_id / "agents" / agent_id / "suffering.jsonl"
        return self._read_file(path, SufferingLog)

    def get_agent_ids(self, run_id: str) -> list[str]:
        agents_dir = self._runs_dir / run_id / "agents"
        if not agents_dir.exists():
            return []
        return [d.name for d in agents_dir.iterdir() if d.is_dir()]

    def get_summary(self, run_id: str) -> dict:
        """Aggregate stats for a run — useful for analysis agents."""
        run = self.get_run(run_id)
        if not run:
            return {}

        agent_ids = self.get_agent_ids(run_id)
        total_goals = 0
        total_completed = 0
        total_abandoned = 0
        total_tool_calls = 0
        total_tokens = 0
        total_cost = 0.0

        for aid in agent_ids:
            goals = self.get_agent_goals(run_id, aid)
            total_goals += len([g for g in goals if g.event == "generated"])
            total_completed += len([g for g in goals if g.event == "completed"])
            total_abandoned += len([g for g in goals if g.event == "abandoned"])

            tools = self.get_agent_tools(run_id, aid)
            total_tool_calls += len(tools)

            decisions = self.get_agent_decisions(run_id, aid)
            for d in decisions:
                total_tokens += d.input_tokens + d.output_tokens
                if d.cost_usd:
                    total_cost += d.cost_usd

        return {
            "run_id": run_id,
            "started_at": run.started_at.isoformat(),
            "heartbeat": run.heartbeat,
            "agents": len(agent_ids),
            "agent_ids": agent_ids,
            "goals_generated": total_goals,
            "goals_completed": total_completed,
            "goals_abandoned": total_abandoned,
            "tool_calls": total_tool_calls,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4),
        }

    def _read_file(self, path: Path, model_cls: type) -> list:
        if not path.exists():
            return []
        records = []
        for line in path.read_text().strip().splitlines():
            if line.strip():
                records.append(model_cls.model_validate_json(line))
        return records

    def _read_jsonl(self, directory: Path, glob_pattern: str, model_cls: type) -> list:
        if not directory.exists():
            return []
        records = []
        for f in sorted(directory.glob(glob_pattern)):
            for line in f.read_text().strip().splitlines():
                if line.strip():
                    records.append(model_cls.model_validate_json(line))
        return records
