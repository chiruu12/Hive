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
    async def test_tool_discovery(self, toolkit):
        tools = toolkit.get_tools()
        names = {t.name for t in tools}
        assert names == {"save_note", "search_notes", "list_recent_notes"}
