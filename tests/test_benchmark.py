"""Tests for benchmark runner and report."""

import json
from pathlib import Path

from hive.benchmark.report import BenchmarkReport
from hive.benchmark.runner import BenchmarkResult, ModelResult


class TestBenchmarkReport:
    def test_to_json(self):
        result = BenchmarkResult(
            scenario="test",
            runs_per_model=1,
            model_results=[
                ModelResult(
                    model="model-a",
                    goals_completed=3,
                    goals_abandoned=1,
                    total_steps=4,
                    total_tokens=500,
                    total_cost=0.01,
                    duration_ms=1000,
                ),
                ModelResult(
                    model="model-b",
                    goals_completed=2,
                    goals_abandoned=2,
                    total_steps=4,
                    total_tokens=400,
                    total_cost=0.005,
                    duration_ms=800,
                    errors=1,
                ),
            ],
        )
        report = BenchmarkReport(result)
        data = json.loads(report.to_json())
        assert data["scenario"] == "test"
        assert len(data["models"]) == 2
        assert data["models"][0]["model"] == "model-a"
        assert data["models"][0]["goals_completed"] == 3
        assert data["models"][1]["errors"] == 1

    def test_save_json(self, tmp_path: Path):
        result = BenchmarkResult(
            scenario="save-test",
            runs_per_model=1,
            model_results=[ModelResult(model="test")],
        )
        report = BenchmarkReport(result)
        out = report.save_json(tmp_path / "results.json")
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["scenario"] == "save-test"

    def test_print_table_no_crash(self):
        result = BenchmarkResult(
            scenario="print-test",
            runs_per_model=1,
            model_results=[
                ModelResult(model="x", goals_completed=1, total_steps=1),
            ],
        )
        report = BenchmarkReport(result)
        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        report.print_table(Console(file=buf, force_terminal=True))
        output = buf.getvalue()
        assert "print-test" in output
