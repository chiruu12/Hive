"""Tests for AgentIdentity chaptered narrative (D3c)."""

from __future__ import annotations

from pathlib import Path

from hive.agents.identity import (
    MAX_CHAPTERS,
    MAX_NARRATIVE,
    AgentIdentity,
    Chapter,
    IdentityManager,
)


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


class TestSealing:
    def _idm_with_agent(self, tmp_path: Path) -> IdentityManager:
        idm = IdentityManager(tmp_path)
        idm.save(AgentIdentity(agent_id="a1", display_name="Atlas"))
        return idm

    def test_no_chapter_below_threshold(self, tmp_path: Path) -> None:
        idm = self._idm_with_agent(tmp_path)
        idm.update_narrative("a1", "small goal", "done")
        ident = idm.load("a1")
        assert ident is not None
        assert ident.chapters == []
        assert "small goal" in ident.narrative

    def test_overflow_seals_chapter_and_preserves_count(self, tmp_path: Path) -> None:
        idm = self._idm_with_agent(tmp_path)
        # Many entries; each ~40 chars, so we cross MAX_NARRATIVE (800) and seal.
        for i in range(40):
            idm.update_narrative("a1", f"goal number {i}", "completed ok")
        ident = idm.load("a1")
        assert ident is not None
        assert len(ident.chapters) >= 1, "no chapter sealed despite overflow"
        # Total entries are conserved across sealed chapters + the open narrative.
        sealed = sum(c.entry_count for c in ident.chapters)
        open_lines = len([ln for ln in ident.narrative.splitlines() if ln.strip()])
        assert sealed + open_lines == 40

    def test_open_narrative_stays_bounded(self, tmp_path: Path) -> None:
        idm = self._idm_with_agent(tmp_path)
        for i in range(60):
            idm.update_narrative("a1", f"goal {i}", "done")
        ident = idm.load("a1")
        assert ident is not None
        # Open narrative never far exceeds the seal threshold.
        assert len(ident.narrative) <= MAX_NARRATIVE + 80

    def test_chapter_indices_monotonic(self, tmp_path: Path) -> None:
        idm = self._idm_with_agent(tmp_path)
        for i in range(80):
            idm.update_narrative("a1", f"goal {i}", "done")
        ident = idm.load("a1")
        assert ident is not None
        indices = [c.index for c in ident.chapters]
        assert indices == sorted(indices)
        assert len(ident.chapters) <= MAX_CHAPTERS


class TestRenderPreamble:
    def test_no_story_section_without_chapters(self, tmp_path: Path) -> None:
        idm = IdentityManager(tmp_path)
        idm.save(AgentIdentity(agent_id="a1", display_name="Atlas", narrative="[01-01] x: y"))
        preamble = idm.build_preamble("a1")
        assert "Story so far" not in preamble
        assert "Recent history" in preamble

    def test_chapters_render_as_story_so_far(self, tmp_path: Path) -> None:
        idm = IdentityManager(tmp_path)
        idm.save(AgentIdentity(agent_id="a1", display_name="Atlas"))
        for i in range(40):
            idm.update_narrative("a1", f"goal {i}", "done")
        preamble = idm.build_preamble("a1")
        assert "Story so far" in preamble
        # The most recent sealed chapter's summary appears.
        ident = idm.load("a1")
        assert ident is not None and ident.chapters
        assert ident.chapters[-1].summary in preamble
