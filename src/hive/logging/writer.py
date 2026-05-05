"""Structured log writer — appends typed records to JSONL files."""

import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from hive.logging.models import (
    CycleLog,
    DecisionLog,
    GoalLog,
    RunLog,
    SufferingLog,
    ToolLog,
)

_lock = threading.Lock()


class LogWriter:
    """Writes structured log records to run-scoped JSONL files."""

    def __init__(self, logs_dir: Path):
        self._logs_dir = logs_dir / "runs"
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        self._run_id: str = ""
        self._run_dir: Path = Path()

    def start_run(
        self,
        heartbeat: int,
        profiles: list[str],
        agents: list[str],
        tools: list[str],
    ) -> str:
        self._run_id = f"run-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
        self._run_dir = self._logs_dir / self._run_id
        self._run_dir.mkdir(parents=True)
        (self._run_dir / "cycles").mkdir()
        (self._run_dir / "agents").mkdir()

        run = RunLog(
            run_id=self._run_id,
            heartbeat=heartbeat,
            profiles=profiles,
            agents_spawned=agents,
            tools_available=tools,
        )
        self._write_json(self._run_dir / "run.json", run.model_dump_json(indent=2))
        return self._run_id

    @property
    def run_id(self) -> str:
        return self._run_id

    def log_cycle(self, cycle: CycleLog) -> None:
        path = self._run_dir / "cycles" / f"cycle_{cycle.cycle:04d}.jsonl"
        self._append(path, cycle.model_dump_json())

    def log_goal(self, goal: GoalLog) -> None:
        agent_dir = self._ensure_agent_dir(goal.agent_id)
        self._append(agent_dir / "goals.jsonl", goal.model_dump_json())

    def log_decision(self, decision: DecisionLog) -> None:
        agent_dir = self._ensure_agent_dir(decision.agent_id)
        self._append(agent_dir / "decisions.jsonl", decision.model_dump_json())

    def log_tool(self, tool: ToolLog) -> None:
        agent_dir = self._ensure_agent_dir(tool.agent_id)
        self._append(agent_dir / "tools.jsonl", tool.model_dump_json())

    def log_suffering(self, suffering: SufferingLog) -> None:
        agent_dir = self._ensure_agent_dir(suffering.agent_id)
        self._append(agent_dir / "suffering.jsonl", suffering.model_dump_json())

    def _ensure_agent_dir(self, agent_id: str) -> Path:
        d = self._run_dir / "agents" / agent_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _append(self, path: Path, line: str) -> None:
        with _lock:
            with open(path, "a") as f:
                f.write(line + "\n")

    def _write_json(self, path: Path, content: str) -> None:
        with _lock:
            path.write_text(content)
