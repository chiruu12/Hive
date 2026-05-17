"""Benchmark report generation — Rich tables and JSON export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from hive.benchmark.runner import BenchmarkResult


class BenchmarkReport:
    """Generate comparison reports from benchmark results."""

    def __init__(self, result: BenchmarkResult):
        self._result = result

    def print_table(self, console: Console | None = None) -> None:
        """Print a Rich comparison table to the terminal."""
        c = console or Console()
        table = Table(title=f"Benchmark: {self._result.scenario}")
        table.add_column("Model", style="cyan")
        table.add_column("Success", style="green")
        table.add_column("Failed", style="red")
        table.add_column("Errors", style="red")
        table.add_column("Steps")
        table.add_column("Tokens")
        table.add_column("Cost", style="yellow")
        table.add_column("Time", style="dim")

        for mr in self._result.model_results:
            rate = f"{mr.goals_completed}/{mr.total_steps}" if mr.total_steps else "0/0"
            table.add_row(
                mr.model,
                rate,
                str(mr.goals_abandoned),
                str(mr.errors),
                str(mr.total_steps),
                f"{mr.total_tokens:,}",
                f"${mr.total_cost:.4f}",
                f"{mr.duration_ms}ms",
            )

        c.print(table)

    def to_json(self) -> str:
        """Export results as JSON."""
        models_list: list[dict[str, Any]] = []
        data: dict[str, Any] = {
            "scenario": self._result.scenario,
            "runs_per_model": self._result.runs_per_model,
            "models": models_list,
        }
        for mr in self._result.model_results:
            models_list.append(
                {
                    "model": mr.model,
                    "goals_completed": mr.goals_completed,
                    "goals_abandoned": mr.goals_abandoned,
                    "total_steps": mr.total_steps,
                    "total_tokens": mr.total_tokens,
                    "total_cost": mr.total_cost,
                    "duration_ms": mr.duration_ms,
                    "errors": mr.errors,
                    "responses": mr.responses,
                }
            )
        return json.dumps(data, indent=2)

    def save_json(self, path: Path) -> Path:
        """Save results as JSON file."""
        path.write_text(self.to_json())
        return path
