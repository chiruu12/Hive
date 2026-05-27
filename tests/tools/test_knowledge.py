"""Tests for KnowledgeToolkit."""

from __future__ import annotations

from pathlib import Path

import pytest

from hive.memory.semantic import SemanticMemory
from hive.tools.knowledge.toolkit import KnowledgeToolkit


@pytest.fixture
def memory(tmp_path: Path) -> SemanticMemory:
    return SemanticMemory(tmp_path, "test-agent")


@pytest.fixture
def toolkit(memory: SemanticMemory) -> KnowledgeToolkit:
    tk = KnowledgeToolkit(memory)
    tk.bind("test-agent")
    return tk


class TestKnowledgeToolkit:
    @pytest.mark.asyncio
    async def test_save_note(self, toolkit):
        result = await toolkit.save_note("Python uses indentation for blocks")
        assert "Saved note" in result
        assert "mem-" in result

    @pytest.mark.asyncio
    async def test_save_note_with_tags(self, toolkit):
        result = await toolkit.save_note("REST APIs use HTTP methods", tags="api,web")
        assert "Saved note" in result

    @pytest.mark.asyncio
    async def test_search_notes(self, toolkit):
        await toolkit.save_note("Python is a programming language")
        await toolkit.save_note("JavaScript runs in the browser")
        await toolkit.save_note("Python has list comprehensions")

        result = await toolkit.search_notes("Python programming")
        assert "Python" in result

    @pytest.mark.asyncio
    async def test_search_notes_empty(self, toolkit):
        result = await toolkit.search_notes("nonexistent topic")
        assert "No matching" in result

    @pytest.mark.asyncio
    async def test_list_recent_notes(self, toolkit):
        await toolkit.save_note("First note")
        await toolkit.save_note("Second note")
        result = await toolkit.list_recent_notes(limit=5)
        assert "First note" in result
        assert "Second note" in result

    @pytest.mark.asyncio
    async def test_list_recent_empty(self, toolkit):
        result = await toolkit.list_recent_notes()
        assert "No notes" in result

    @pytest.mark.asyncio
    async def test_tags_in_search_results(self, toolkit):
        await toolkit.save_note("Docker containers are isolated", tags="devops")
        result = await toolkit.search_notes("Docker")
        assert "devops" in result

    @pytest.mark.asyncio
    async def test_delete_note(self, toolkit):
        result = await toolkit.save_note("Temporary note")
        note_id = result.split()[2].rstrip(":")
        delete_result = await toolkit.delete_note(note_id)
        assert "deleted" in delete_result

        listing = await toolkit.list_recent_notes()
        assert "Temporary note" not in listing

    @pytest.mark.asyncio
    async def test_delete_nonexistent_note(self, toolkit):
        result = await toolkit.delete_note("mem-nonexistent")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_update_note_content(self, toolkit):
        result = await toolkit.save_note("Original content")
        note_id = result.split()[2].rstrip(":")
        update = await toolkit.update_note(note_id, content="Updated content")
        assert "updated" in update

        search = await toolkit.search_notes("Updated content")
        assert "Updated" in search

    @pytest.mark.asyncio
    async def test_update_note_tags(self, toolkit):
        result = await toolkit.save_note("Tagged note", tags="old-tag")
        note_id = result.split()[2].rstrip(":")
        await toolkit.update_note(note_id, tags="new-tag")

        listing = await toolkit.list_recent_notes()
        assert "new-tag" in listing

    @pytest.mark.asyncio
    async def test_update_nonexistent_note(self, toolkit):
        result = await toolkit.update_note("mem-nonexistent", content="nope")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_tool_discovery(self, toolkit):
        tools = toolkit.get_tools()
        names = {t.name for t in tools}
        assert names == {
            "save_note",
            "search_notes",
            "list_recent_notes",
            "delete_note",
            "update_note",
        }

    @pytest.mark.asyncio
    async def test_rebind_creates_new_memory(self, tmp_path):
        """rebind() must create a fresh SemanticMemory for the new agent."""
        tk = KnowledgeToolkit(memory_dir=tmp_path)
        tk.bind("agent-a")
        await tk.save_note("Agent A's secret note")

        tk.rebind("agent-b")
        assert tk._agent_id == "agent-b"
        result = await tk.search_notes("secret")
        assert "No matching" in result
