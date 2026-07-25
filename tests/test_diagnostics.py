"""Tests for hive doctor diagnostics."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from hive.daemon.diagnostics import (
    CheckResult,
    check_budget_ledger,
    check_dependencies,
    check_hive_dir,
    check_plugins_dir,
    check_profiles_dir,
    check_python_version,
    check_sqlite_integrity,
    check_stale_pid,
    run_all_checks,
)


class TestCheckPythonVersion:
    def test_returns_ok(self) -> None:
        result = check_python_version()
        assert result.status == "ok"
        assert "." in result.message


class TestCheckDependencies:
    def test_returns_ok(self) -> None:
        result = check_dependencies()
        assert result.status == "ok"
        assert result.message == "All installed"


class TestCheckHiveDir:
    def test_existing_dir(self, tmp_path: Path) -> None:
        hive = tmp_path / ".hive"
        hive.mkdir()
        (hive / "hive.db").touch()
        (hive / "config.yaml").touch()
        result = check_hive_dir(hive)
        assert result.status == "ok"

    def test_missing_dir(self, tmp_path: Path) -> None:
        result = check_hive_dir(tmp_path / "nonexistent")
        assert result.status == "fail"
        assert "Not found" in result.message
        assert result.fix

    def test_incomplete_dir(self, tmp_path: Path) -> None:
        hive = tmp_path / ".hive"
        hive.mkdir()
        result = check_hive_dir(hive)
        assert result.status == "warn"
        assert "Missing" in result.message


class TestCheckSqliteIntegrity:
    def test_valid_db(self, tmp_path: Path) -> None:
        hive = tmp_path / ".hive"
        hive.mkdir()
        db_path = hive / "hive.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id TEXT)")
        conn.close()
        result = check_sqlite_integrity(hive)
        assert result.status == "ok"

    def test_no_db(self, tmp_path: Path) -> None:
        hive = tmp_path / ".hive"
        hive.mkdir()
        result = check_sqlite_integrity(hive)
        assert result.status == "warn"


class TestRunAllChecks:
    def test_returns_list(self, tmp_path: Path) -> None:
        results = run_all_checks(tmp_path / ".hive")
        assert isinstance(results, list)
        assert len(results) >= 6
        assert all(isinstance(r, CheckResult) for r in results)

    def test_check_names_unique(self, tmp_path: Path) -> None:
        results = run_all_checks(tmp_path / ".hive")
        names = [r.name for r in results]
        assert len(names) == len(set(names))


class TestExtendedChecks:
    def test_stale_pid_fails(self, tmp_path: Path) -> None:
        hive = tmp_path / ".hive"
        hive.mkdir()
        (hive / "daemon.pid").write_text("99999999")
        result = check_stale_pid(hive)
        assert result.status == "fail"
        assert "Stale" in result.message

    def test_budget_ledger_readable(self, tmp_path: Path) -> None:
        hive = tmp_path / ".hive"
        hive.mkdir()
        config = hive / "config.yaml"
        config.write_text("daemon:\n  budget_persist: true\n  budget_usd: 1.0\n")
        ledger = hive / "budget.json"
        ledger.write_text('{"spent_usd": 0.25, "spent_tokens": 100}\n')
        result = check_budget_ledger(hive)
        assert result.status == "ok"
        assert "budget.json" in result.message

    def test_profiles_dir_resolves_from_config(self, tmp_path: Path, monkeypatch) -> None:
        hive = tmp_path / ".hive"
        hive.mkdir()
        repo_profiles = Path(__file__).resolve().parents[1] / "profiles"
        (hive / "config.yaml").write_text(f'profiles_dir: "{repo_profiles}"\n')
        (hive / "hive.db").touch()
        monkeypatch.chdir(tmp_path)
        result = check_profiles_dir(hive)
        assert result.status == "ok"

    def test_plugins_dir_missing_ok(self, tmp_path: Path) -> None:
        hive = tmp_path / ".hive"
        hive.mkdir()
        (hive / "config.yaml").write_text("plugins:\n  enabled: false\n")
        result = check_plugins_dir(hive)
        assert result.status == "ok"
