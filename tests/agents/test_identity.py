"""Tests for AgentIdentity chaptered narrative (D3c)."""

from __future__ import annotations

from pathlib import Path

from hive.agents.identity import AgentIdentity, Chapter, IdentityManager


class TestChapterModel:
    def test_chapters_default_empty(self) -> None:
        ident = AgentIdentity(agent_id="a1", display_name="Atlas")
        assert ident.chapters == []

    def test_legacy_json_without_chapters_loads_empty(self) -> None:
        """An identity serialized before chapters existed still loads."""
        legacy = '{"agent_id": "a1", "display_name": "Atlas", "narrative": "old"}'
        ident = AgentIdentity.model_validate_json(legacy)
        assert ident.chapters == []
        assert ident.narrative == "old"

    def test_chapter_round_trip(self) -> None:
        ident = AgentIdentity(
            agent_id="a1",
            display_name="Atlas",
            chapters=[Chapter(index=1, summary="Ch1: 5 entries", entry_count=5)],
        )
        restored = AgentIdentity.model_validate_json(ident.model_dump_json())
        assert len(restored.chapters) == 1
        assert restored.chapters[0].index == 1
        assert restored.chapters[0].entry_count == 5

    def test_manager_persists_chapters(self, tmp_path: Path) -> None:
        idm = IdentityManager(tmp_path)
        ident = AgentIdentity(
            agent_id="a1",
            display_name="Atlas",
            chapters=[Chapter(index=1, summary="Ch1", entry_count=3)],
        )
        idm.save(ident)
        loaded = idm.load("a1")
        assert loaded is not None
        assert len(loaded.chapters) == 1
