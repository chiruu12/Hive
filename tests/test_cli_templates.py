"""Tests for project scaffolding templates."""

from __future__ import annotations

from pathlib import Path

import pytest

from hive.cli.templates import scaffold_project, validate_project_name


class TestValidateProjectName:
    def test_valid_names(self):
        assert validate_project_name("my-project") is None
        assert validate_project_name("my_project") is None
        assert validate_project_name("project123") is None
        assert validate_project_name("a") is None

    def test_empty_name(self):
        assert validate_project_name("") is not None

    def test_invalid_chars(self):
        assert validate_project_name("my project") is not None
        assert validate_project_name("my@project") is not None

    def test_too_long(self):
        assert validate_project_name("a" * 65) is not None
        assert validate_project_name("a" * 64) is None


class TestScaffoldProject:
    def test_minimal_template(self, tmp_path: Path):
        hive_dir = scaffold_project("test", "minimal", tmp_path)
        assert (hive_dir / "config.yaml").exists()
        # Profiles live at the project root, where hive start/spawn look.
        assert (tmp_path / "profiles" / "assistant.yaml").exists()
        assert (hive_dir / "README.md").exists()
        config = (hive_dir / "config.yaml").read_text()
        # heartbeat must be nested under daemon: so the schema picks it up.
        assert "daemon:" in config
        assert "heartbeat" in config

    def test_config_loads_and_applies(self, tmp_path: Path):
        from hive.config import HiveConfig

        scaffold_project("test", "minimal", tmp_path)
        cfg = HiveConfig.load(tmp_path / ".hive")
        assert cfg.daemon.heartbeat == 30

    def test_team_template(self, tmp_path: Path):
        scaffold_project("team", "team", tmp_path)
        profiles = list((tmp_path / "profiles").glob("*.yaml"))
        assert len(profiles) == 3
        names = {p.stem for p in profiles}
        assert names == {"architect", "developer", "reviewer"}

    def test_research_template(self, tmp_path: Path):
        scaffold_project("research", "research", tmp_path)
        profiles = list((tmp_path / "profiles").glob("*.yaml"))
        assert len(profiles) == 2
        names = {p.stem for p in profiles}
        assert names == {"researcher", "analyst"}

    def test_raises_on_existing_without_force(self, tmp_path: Path):
        scaffold_project("test", "minimal", tmp_path)
        with pytest.raises(FileExistsError):
            scaffold_project("test", "minimal", tmp_path)

    def test_force_overwrites(self, tmp_path: Path):
        scaffold_project("test", "minimal", tmp_path)
        scaffold_project("test", "team", tmp_path, force=True)
        profiles = list((tmp_path / "profiles").glob("*.yaml"))
        # The three team profiles plus the minimal 'assistant' left in place
        # (force overwrites template files, never deletes unrelated ones).
        names = {p.stem for p in profiles}
        assert {"architect", "developer", "reviewer"} <= names

    def test_force_preserves_unrelated_profiles(self, tmp_path: Path):
        scaffold_project("test", "minimal", tmp_path)
        (tmp_path / "profiles" / "custom.yaml").write_text("name: custom\nrole: x\n")
        scaffold_project("test", "team", tmp_path, force=True)
        assert (tmp_path / "profiles" / "custom.yaml").exists()

    def test_invalid_name(self, tmp_path: Path):
        with pytest.raises(ValueError):
            scaffold_project("bad name!", "minimal", tmp_path)

    def test_invalid_template(self, tmp_path: Path):
        with pytest.raises(ValueError):
            scaffold_project("test", "nonexistent", tmp_path)

    def test_readme_contains_name(self, tmp_path: Path):
        hive_dir = scaffold_project("myapp", "minimal", tmp_path)
        readme = (hive_dir / "README.md").read_text()
        assert "myapp" in readme
