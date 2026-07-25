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


class TestStopCommand:
    def test_stop_without_pidfile(self, in_tmp_cwd: Path) -> None:
        _init(in_tmp_cwd)
        result = runner.invoke(app, ["stop"])
        assert result.exit_code == 1
        assert "no daemon" in result.output.lower() or "not running" in result.output.lower()

    def test_stop_with_stale_pidfile(self, in_tmp_cwd: Path) -> None:
        _init(in_tmp_cwd)
        pid_file = in_tmp_cwd / ".hive" / "daemon.pid"
        pid_file.write_text("99999999")  # PID that almost certainly doesn't exist
        result = runner.invoke(app, ["stop"])
        assert result.exit_code == 0
        assert "not found" in result.output.lower() or "stale" in result.output.lower()
        assert not pid_file.exists()

    def test_stop_with_invalid_pidfile(self, in_tmp_cwd: Path) -> None:
        _init(in_tmp_cwd)
        pid_file = in_tmp_cwd / ".hive" / "daemon.pid"
        pid_file.write_text("not_a_number")
        result = runner.invoke(app, ["stop"])
        assert result.exit_code == 1
        assert "invalid" in result.output.lower()


class TestRestartCommand:
    def test_restart_guard_requires_init(self, in_tmp_cwd: Path) -> None:
        result = runner.invoke(app, ["restart"])
        assert result.exit_code == 1
        assert "init" in result.output.lower()


class TestBudgetStandalone:
    def test_budget_status_from_ledger_without_rest(self, in_tmp_cwd: Path) -> None:
        _init(in_tmp_cwd)
        config = in_tmp_cwd / ".hive" / "config.yaml"
        config.write_text(
            "daemon:\n  budget_persist: true\n  budget_usd: 5.0\n  budget_tokens: 1000\n"
        )
        ledger = in_tmp_cwd / ".hive" / "budget.json"
        ledger.write_text('{"spent_usd": 1.25, "spent_tokens": 200}\n')
        result = runner.invoke(app, ["budget"])
        assert result.exit_code == 0
        assert "1.2500" in result.output
        assert "standalone" in result.output.lower()

    def test_budget_reset_writes_ledger(self, in_tmp_cwd: Path) -> None:
        _init(in_tmp_cwd)
        config = in_tmp_cwd / ".hive" / "config.yaml"
        config.write_text("daemon:\n  budget_persist: true\n")
        ledger = in_tmp_cwd / ".hive" / "budget.json"
        ledger.write_text('{"spent_usd": 9.0, "spent_tokens": 900}\n')
        result = runner.invoke(app, ["budget", "reset"])
        assert result.exit_code == 0
        import json

        data = json.loads(ledger.read_text())
        assert data["spent_usd"] == 0.0
        assert data["spent_tokens"] == 0

    def test_budget_status_falls_back_on_non_200(self, in_tmp_cwd: Path, monkeypatch) -> None:
        """503 from serve-without-daemon falls through to ledger snapshot."""
        _init(in_tmp_cwd)
        config = in_tmp_cwd / ".hive" / "config.yaml"
        config.write_text(
            "daemon:\n  budget_persist: true\n  budget_usd: 5.0\n  budget_tokens: 1000\n"
        )
        ledger = in_tmp_cwd / ".hive" / "budget.json"
        ledger.write_text('{"spent_usd": 2.5, "spent_tokens": 400}\n')

        class _FakeResponse:
            status_code = 503

            def json(self) -> dict[str, object]:
                return {}

        class _FakeClient:
            def get(self, *args: object, **kwargs: object) -> _FakeResponse:
                return _FakeResponse()

        monkeypatch.setattr("httpx.get", _FakeClient().get)
        result = runner.invoke(app, ["budget"])
        assert result.exit_code == 0
        assert "2.5000" in result.output
        assert "standalone" in result.output.lower()


class TestSpawnBundledProfiles:
    def test_spawn_uses_config_profiles_dir(self, in_tmp_cwd: Path) -> None:
        _init(in_tmp_cwd)
        repo_profiles = Path(__file__).resolve().parents[2] / "profiles"
        config = in_tmp_cwd / ".hive" / "config.yaml"
        config.write_text(f'profiles_dir: "{repo_profiles}"\n')
        result = runner.invoke(app, ["spawn", "researcher"])
        assert result.exit_code == 0
        assert "Spawned" in result.output


class TestConfigTruth:
    def test_config_effective_flag(self, in_tmp_cwd: Path) -> None:
        _init(in_tmp_cwd)
        result = runner.invoke(app, ["config", "--effective"])
        assert result.exit_code == 0
        assert "Effective Configuration" in result.output

    def test_config_set_shows_restart_warning(self, in_tmp_cwd: Path) -> None:
        _init(in_tmp_cwd)
        result = runner.invoke(app, ["config", "guardrails.enabled", "true"])
        assert result.exit_code == 0
        assert "restart required" in result.output.lower()


class TestDoctorExitCode:
    def test_doctor_fails_on_stale_pid(self, in_tmp_cwd: Path) -> None:
        _init(in_tmp_cwd)
        (in_tmp_cwd / ".hive" / "daemon.pid").write_text("99999999")
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 1
        assert "Stale" in result.output or "critical" in result.output.lower()


class TestDaemonHealthCommand:
    def test_daemon_not_running(self, in_tmp_cwd: Path) -> None:
        _init(in_tmp_cwd)
        result = runner.invoke(app, ["daemon"])
        assert result.exit_code == 1
        assert "not running" in result.output.lower()

    def test_daemon_status_budget_ledger_fallback(
        self, in_tmp_cwd: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When REST budget returns 503, daemon status shows ledger fallback."""
        import os

        _init(in_tmp_cwd)
        config = in_tmp_cwd / ".hive" / "config.yaml"
        config.write_text(
            "daemon:\n  budget_persist: true\n  budget_usd: 5.0\n  budget_tokens: 1000\n"
        )
        ledger = in_tmp_cwd / ".hive" / "budget.json"
        ledger.write_text('{"spent_usd": 0.75, "spent_tokens": 150}\n')
        (in_tmp_cwd / ".hive" / "daemon.pid").write_text(str(os.getpid()))

        class _Budget503:
            status_code = 503

            def json(self) -> dict[str, object]:
                return {}

        class _Status404:
            status_code = 404

            def json(self) -> list[object]:
                return []

        def _fake_get(url: str, *args: object, **kwargs: object) -> object:
            if url.endswith("/budget"):
                return _Budget503()
            return _Status404()

        monkeypatch.setattr("httpx.get", _fake_get)
        result = runner.invoke(app, ["daemon"])
        assert result.exit_code == 0
        assert "0.7500" in result.output
        assert "ledger fallback" in result.output.lower()


class TestNewCommand:
    def test_new_minimal(self, in_tmp_cwd: Path) -> None:
        result = runner.invoke(app, ["new", "myproject", "--template", "minimal"])
        assert result.exit_code == 0
        # scaffold_project creates .hive/ directly in cwd, not in a subdirectory
        assert (in_tmp_cwd / ".hive" / "config.yaml").exists()
        assert (in_tmp_cwd / "profiles" / "assistant.yaml").exists()

    def test_new_team(self, in_tmp_cwd: Path) -> None:
        result = runner.invoke(app, ["new", "teamproject", "--template", "team"])
        assert result.exit_code == 0
        profiles = in_tmp_cwd / "profiles"
        assert (profiles / "architect.yaml").exists()
        assert (profiles / "developer.yaml").exists()
        assert (profiles / "reviewer.yaml").exists()

    def test_new_invalid_name(self, in_tmp_cwd: Path) -> None:
        result = runner.invoke(app, ["new", "bad name!", "--template", "minimal"])
        assert result.exit_code == 1

    def test_new_invalid_template(self, in_tmp_cwd: Path) -> None:
        result = runner.invoke(app, ["new", "proj", "--template", "nonexistent"])
        assert result.exit_code == 1

    def test_new_existing_dir_without_force(self, in_tmp_cwd: Path) -> None:
        runner.invoke(app, ["new", "proj", "--template", "minimal"])
        result = runner.invoke(app, ["new", "proj", "--template", "minimal"])
        assert result.exit_code == 1
