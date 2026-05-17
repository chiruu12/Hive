"""Tests for HTML report export."""

import json
from pathlib import Path

import pytest

from hive.export.html import export_html_report


@pytest.fixture
def run_dir(tmp_path: Path) -> tuple[str, Path]:
    """Create a minimal run structure for testing."""
    run_id = "run-test-001"
    runs = tmp_path / "logs" / "runs" / run_id
    runs.mkdir(parents=True)

    run_meta = {
        "run_id": run_id,
        "started_at": "2026-05-16T10:00:00",
        "heartbeat": 10,
        "profiles": ["coder"],
        "agents_spawned": ["agent-a"],
        "tools": ["work", "learn"],
    }
    (runs / "run.json").write_text(json.dumps(run_meta))

    agent_dir = runs / "agents" / "agent-a"
    agent_dir.mkdir(parents=True)

    goal = {
        "agent_id": "agent-a",
        "goal_id": "g-1",
        "event": "completed",
        "objective": "Learn Python basics",
    }
    (agent_dir / "goals.jsonl").write_text(json.dumps(goal) + "\n")

    decision = {
        "agent_id": "agent-a",
        "decision_type": "existence",
        "model": "test-model",
        "input_tokens": 100,
        "output_tokens": 50,
        "cost_usd": 0.001,
        "duration_ms": 500,
        "response_raw": "test",
        "success": True,
    }
    (agent_dir / "decisions.jsonl").write_text(json.dumps(decision) + "\n")

    return run_id, tmp_path


class TestHtmlExport:
    def test_generates_html_file(self, run_dir: tuple[str, Path]):
        run_id, base = run_dir
        output = base / "report.html"
        result = export_html_report(run_id, base / "logs", output)
        assert result.exists()
        content = result.read_text()
        assert "<!DOCTYPE html>" in content
        assert run_id in content

    def test_includes_agent_data(self, run_dir: tuple[str, Path]):
        run_id, base = run_dir
        output = base / "report.html"
        export_html_report(run_id, base / "logs", output)
        content = output.read_text()
        assert "agent-a" in content
        assert "Learn Python basics" in content

    def test_includes_stats(self, run_dir: tuple[str, Path]):
        run_id, base = run_dir
        output = base / "report.html"
        export_html_report(run_id, base / "logs", output)
        content = output.read_text()
        assert "150" in content  # 100 + 50 tokens
        assert "$0.001" in content

    def test_unknown_run_raises(self, tmp_path: Path):
        logs = tmp_path / "logs"
        logs.mkdir()
        with pytest.raises(ValueError, match="not found"):
            export_html_report("nonexistent", logs, tmp_path / "out.html")

    def test_includes_notepad(self, run_dir: tuple[str, Path]):
        run_id, base = run_dir
        hive_dir = base / ".hive"
        journals = hive_dir / "journals" / "agent-a"
        journals.mkdir(parents=True)
        (journals / "notepad.md").write_text("My important observation.")

        output = base / "report.html"
        export_html_report(run_id, base / "logs", output, hive_dir=hive_dir)
        content = output.read_text()
        assert "My important observation" in content

    def test_dark_theme_css(self, run_dir: tuple[str, Path]):
        run_id, base = run_dir
        output = base / "report.html"
        export_html_report(run_id, base / "logs", output)
        content = output.read_text()
        assert "--bg: #1a1b26" in content
