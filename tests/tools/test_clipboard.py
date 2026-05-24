"""Tests for ClipboardToolkit."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from hive.memory.semantic import SemanticMemory
from hive.tools.clipboard.toolkit import ClipboardToolkit


@pytest.fixture
def memory(tmp_path: Path) -> SemanticMemory:
    return SemanticMemory(tmp_path, "test-agent")


@pytest.fixture
def toolkit(memory: SemanticMemory) -> ClipboardToolkit:
    tk = ClipboardToolkit(memory=memory)
    tk.bind("test-agent")
    return tk


class TestClipboardToolkit:
    def test_standalone_creation(self) -> None:
        tk = ClipboardToolkit()
        tk.bind("agent")
        tools = tk.get_tools()
        tool_names = {t.name for t in tools}
        assert "copy_to_clipboard" in tool_names
        assert "copy_note" in tool_names
        assert "copy_task" in tool_names
        assert "copy_link" in tool_names

    @pytest.mark.asyncio
    async def test_copy_to_clipboard(self, toolkit: ClipboardToolkit) -> None:
        with patch(
            "hive.tools.clipboard.toolkit._copy_to_system_clipboard",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await toolkit.copy_to_clipboard("hello world")
        assert "Copied to clipboard" in result
        assert "hello world" in result

    @pytest.mark.asyncio
    async def test_copy_to_clipboard_failure(self, toolkit: ClipboardToolkit) -> None:
        with patch(
            "hive.tools.clipboard.toolkit._copy_to_system_clipboard",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await toolkit.copy_to_clipboard("test")
        assert "Failed" in result

    @pytest.mark.asyncio
    async def test_copy_note(self, toolkit: ClipboardToolkit, memory: SemanticMemory) -> None:
        mid = await memory.store("Important meeting notes", {"tags": "work"})
        with patch(
            "hive.tools.clipboard.toolkit._copy_to_system_clipboard",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await toolkit.copy_note(mid)
        assert "Copied note" in result
        assert "Important meeting notes" in result

    @pytest.mark.asyncio
    async def test_copy_note_not_found(self, toolkit: ClipboardToolkit) -> None:
        result = await toolkit.copy_note("nonexistent")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_copy_note_no_memory(self) -> None:
        tk = ClipboardToolkit()
        tk.bind("agent")
        result = await tk.copy_note("some-id")
        assert "No knowledge base" in result

    @pytest.mark.asyncio
    async def test_copy_link(self, toolkit: ClipboardToolkit, memory: SemanticMemory) -> None:
        await memory.store(
            "Python docs",
            {"type": "link", "url": "https://python.org", "title": "Python"},
        )
        with patch(
            "hive.tools.clipboard.toolkit._copy_to_system_clipboard",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await toolkit.copy_link("python")
        assert "Copied URL" in result
        assert "python.org" in result

    @pytest.mark.asyncio
    async def test_copy_link_not_found(self, toolkit: ClipboardToolkit) -> None:
        result = await toolkit.copy_link("nonexistent-thing-xyz")
        assert "No saved link" in result

    @pytest.mark.asyncio
    async def test_copy_task_no_store(self) -> None:
        tk = ClipboardToolkit()
        tk.bind("agent")
        result = await tk.copy_task("task-123")
        assert "No task store" in result
