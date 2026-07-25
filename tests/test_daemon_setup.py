"""Tests for daemon setup (ensure_hive_dirs, initialize_hive)."""

from __future__ import annotations

from pathlib import Path

from hive.daemon.setup import ensure_hive_dirs, initialize_hive


class TestEnsureHiveDirs:
    def test_creates_hive_directory(self, tmp_path: Path):
        result = ensure_hive_dirs(tmp_path)
        assert result == tmp_path / ".hive"
        assert result.exists()
        assert result.is_dir()

    def test_creates_subdirectories(self, tmp_path: Path):
        ensure_hive_dirs(tmp_path)
        assert (tmp_path / ".hive" / "sessions").is_dir()
        assert (tmp_path / ".hive" / "workspaces").is_dir()

    def test_creates_config_yaml(self, tmp_path: Path):
        ensure_hive_dirs(tmp_path)
        config_path = tmp_path / ".hive" / "config.yaml"
        assert config_path.exists()

    def test_idempotent(self, tmp_path: Path):
        result1 = ensure_hive_dirs(tmp_path)
        result2 = ensure_hive_dirs(tmp_path)
        assert result1 == result2
        # Should not error on second call

    def test_creates_gitignore(self, tmp_path: Path):
        ensure_hive_dirs(tmp_path)
        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        assert ".hive/" in gitignore.read_text()

    def test_appends_to_existing_gitignore(self, tmp_path: Path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n__pycache__/\n")
        ensure_hive_dirs(tmp_path)
        content = gitignore.read_text()
        assert "*.pyc" in content
        assert ".hive/" in content

    def test_no_duplicate_gitignore_entry(self, tmp_path: Path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".hive/\n")
        ensure_hive_dirs(tmp_path)
        content = gitignore.read_text()
        assert content.count(".hive/") == 1

    def test_gitignore_no_trailing_newline(self, tmp_path: Path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc")
        ensure_hive_dirs(tmp_path)
        content = gitignore.read_text()
        assert ".hive/" in content

    def test_preserves_existing_config(self, tmp_path: Path):
        ensure_hive_dirs(tmp_path)
        config_path = tmp_path / ".hive" / "config.yaml"

        # Modify config
        config_path.write_text("custom: value\n")

        # Calling again should NOT overwrite
        ensure_hive_dirs(tmp_path)
        assert config_path.read_text() == "custom: value\n"


class TestInitializeHive:
    def test_creates_database(self, tmp_path: Path):
        initialize_hive(tmp_path)
        db_path = tmp_path / ".hive" / "hive.db"
        assert db_path.exists()

    def test_creates_all_structure(self, tmp_path: Path):
        initialize_hive(tmp_path)
        assert (tmp_path / ".hive").is_dir()
        assert (tmp_path / ".hive" / "sessions").is_dir()
        assert (tmp_path / ".hive" / "workspaces").is_dir()
        assert (tmp_path / ".hive" / "nudges").is_dir()
        assert (tmp_path / ".hive" / "config.yaml").exists()
        assert (tmp_path / ".hive" / "hive.db").exists()
