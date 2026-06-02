"""CLI smoke/behavior tests via Typer's CliRunner (F1 coverage).

Covers the read-only / no-daemon commands: argument parsing, exit codes, and
error paths. The async TUI/daemon commands (start, watch, orchestrate, agent
chat) are out of scope here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from hive.cli.main import app

runner = CliRunner()


@pytest.fixture
def in_tmp_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run each command inside an isolated cwd (the CLI uses Path.cwd()/.hive)."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _init(in_tmp_cwd: Path) -> None:
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0


def _write_profile(cwd: Path, name: str = "coder") -> None:
    """Make `name`.yaml available to `hive spawn`, which reads cwd/profiles."""
    dest_dir = cwd / "profiles"
    dest_dir.mkdir(exist_ok=True)
    (dest_dir / f"{name}.yaml").write_text(
        f'name: {name}\nrole: "Test agent"\nmodel: claude-haiku-4-5\nautonomy: high\nmax_steps: 5\n'
    )


class TestInit:
    def test_init_creates_hive(self, in_tmp_cwd: Path) -> None:
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert (in_tmp_cwd / ".hive").is_dir()
        assert (in_tmp_cwd / ".hive" / "hive.db").exists()

    def test_init_idempotent(self, in_tmp_cwd: Path) -> None:
        runner.invoke(app, ["init"])
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert "already initialized" in result.output.lower()


class TestGuardsRequireInit:
    @pytest.mark.parametrize(
        "args",
        [["status"], ["spawn", "coder"], ["kill", "x"], ["nudge", "x", "hi"], ["tasks"]],
    )
    def test_commands_exit_1_without_hive(self, in_tmp_cwd: Path, args: list[str]) -> None:
        result = runner.invoke(app, args)
        assert result.exit_code == 1
        assert "init" in result.output.lower()


class TestStatus:
    def test_status_empty(self, in_tmp_cwd: Path) -> None:
        _init(in_tmp_cwd)
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "No agents" in result.output


class TestSpawn:
    def test_spawn_unknown_profile(self, in_tmp_cwd: Path) -> None:
        _init(in_tmp_cwd)
        result = runner.invoke(app, ["spawn", "ghost"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_spawn_success_then_status_lists_it(self, in_tmp_cwd: Path) -> None:
        _init(in_tmp_cwd)
        _write_profile(in_tmp_cwd, "coder")
        result = runner.invoke(app, ["spawn", "coder"])
        assert result.exit_code == 0
        assert "Spawned" in result.output

        status = runner.invoke(app, ["status"])
        assert "coder" in status.output


class TestAgentLookupErrors:
    def test_kill_unknown_agent(self, in_tmp_cwd: Path) -> None:
        _init(in_tmp_cwd)
        result = runner.invoke(app, ["kill", "nobody"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_nudge_unknown_agent(self, in_tmp_cwd: Path) -> None:
        _init(in_tmp_cwd)
        result = runner.invoke(app, ["nudge", "nobody", "do the thing"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()


class TestReadOnlyListings:
    def test_tasks_empty(self, in_tmp_cwd: Path) -> None:
        _init(in_tmp_cwd)
        result = runner.invoke(app, ["tasks"])
        assert result.exit_code == 0
        assert "No pending tasks" in result.output

    def test_notes_empty(self, in_tmp_cwd: Path) -> None:
        _init(in_tmp_cwd)
        result = runner.invoke(app, ["notes"])
        assert result.exit_code == 0
        assert "No notes" in result.output

    def test_runs_empty(self, in_tmp_cwd: Path) -> None:
        result = runner.invoke(app, ["runs"])
        assert result.exit_code == 0
        assert "No runs" in result.output

    def test_models_runs_without_hive(self, in_tmp_cwd: Path) -> None:
        # `models` inspects providers; it must not require an initialized hive.
        result = runner.invoke(app, ["models"])
        assert result.exit_code == 0


class TestHelp:
    def test_no_args_shows_help(self) -> None:
        result = runner.invoke(app, [])
        # no_args_is_help=True -> usage shown, non-crashing exit.
        assert "Usage" in result.output or "Commands" in result.output
