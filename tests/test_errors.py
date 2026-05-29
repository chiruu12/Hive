"""Tests for the typed error hierarchy (Phase 1 E1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hive.agents.profile import AgentProfile
from hive.api import Hive
from hive.errors import AgentNotFoundError, HiveError, ProfileNotFoundError


class TestErrorHierarchy:
    def test_agent_not_found_is_hive_error_and_value_error(self) -> None:
        # Subclasses ValueError so pre-existing `except ValueError` handlers keep working.
        assert issubclass(AgentNotFoundError, HiveError)
        assert issubclass(AgentNotFoundError, ValueError)

    def test_profile_not_found_is_hive_error_and_file_not_found(self) -> None:
        assert issubclass(ProfileNotFoundError, HiveError)
        assert issubclass(ProfileNotFoundError, FileNotFoundError)


class TestErrorsRaised:
    def test_resolve_missing_agent_raises_typed(self, tmp_path: Path) -> None:
        h = Hive(tmp_path)
        h.init()
        with pytest.raises(AgentNotFoundError):
            h._resolve_agent("nope")
        # Still catchable as the builtin it replaced.
        with pytest.raises(ValueError):
            h._resolve_agent("nope")

    def test_kill_missing_agent_raises_typed(self, tmp_path: Path) -> None:
        h = Hive(tmp_path)
        h.init()
        with pytest.raises(HiveError):
            h.kill("ghost")

    def test_from_preset_missing_raises_typed(self, tmp_path: Path) -> None:
        with pytest.raises(ProfileNotFoundError):
            AgentProfile.from_preset("does-not-exist", tmp_path)
        with pytest.raises(FileNotFoundError):
            AgentProfile.from_preset("does-not-exist", tmp_path)
