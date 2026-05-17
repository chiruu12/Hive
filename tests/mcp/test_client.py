"""Tests for MCPToolkit — MCP server tools as Hive Tools."""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from hive.tools import Tool
from hive.tools.mcp import MCPToolkit


def _make_mcp_tool(
    name: str = "test_tool",
    description: str = "A test tool",
    input_schema: dict[str, Any] | None = None,
) -> MagicMock:
    """Create a mock MCP Tool object."""
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.inputSchema = input_schema or {
        "type": "object",
        "properties": {"arg1": {"type": "string"}},
    }
    return tool


def _make_call_result(
    text: str = "result",
    is_error: bool = False,
) -> MagicMock:
    """Create a mock CallToolResult."""
    content_block = MagicMock()
    content_block.text = text
    result = MagicMock()
    result.content = [content_block]
    result.isError = is_error
    return result


def _make_toolkit(
    mcp_tools: list[Any] | None = None,
    session: Any = None,
) -> MCPToolkit:
    """Create an MCPToolkit with mock session and tools."""
    if mcp_tools is None:
        mcp_tools = [_make_mcp_tool()]
    if session is None:
        session = AsyncMock()
    return MCPToolkit(
        session=session,
        context_stack=AsyncExitStack(),
        mcp_tools=mcp_tools,
        server_name="mock-server",
    )


class TestMCPToolConversion:
    def test_single_tool(self) -> None:
        toolkit = _make_toolkit()
        tools = toolkit.get_tools()
        assert len(tools) == 1
        assert isinstance(tools[0], Tool)
        assert tools[0].name == "test_tool"
        assert tools[0].description == "A test tool"
        assert tools[0].is_async is True

    def test_multiple_tools(self) -> None:
        mcp_tools = [
            _make_mcp_tool("read", "Read a file"),
            _make_mcp_tool("write", "Write a file"),
            _make_mcp_tool("list", "List files"),
        ]
        toolkit = _make_toolkit(mcp_tools=mcp_tools)
        tools = toolkit.get_tools()
        assert len(tools) == 3
        names = {t.name for t in tools}
        assert names == {"read", "write", "list"}

    def test_no_description_fallback(self) -> None:
        tool_mock = _make_mcp_tool(description=None)
        toolkit = _make_toolkit(mcp_tools=[tool_mock])
        tools = toolkit.get_tools()
        assert tools[0].description == "(no description)"

    def test_schema_preserved(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "recursive": {"type": "boolean"},
            },
            "required": ["path"],
        }
        tool_mock = _make_mcp_tool(input_schema=schema)
        toolkit = _make_toolkit(mcp_tools=[tool_mock])
        tools = toolkit.get_tools()
        assert tools[0].parameters == schema

    def test_tool_count(self) -> None:
        toolkit = _make_toolkit(mcp_tools=[_make_mcp_tool(), _make_mcp_tool("b")])
        assert toolkit.tool_count == 2

    def test_server_name(self) -> None:
        toolkit = _make_toolkit()
        assert toolkit.server_name == "mock-server"


class TestMCPToolExecution:
    @pytest.mark.asyncio
    async def test_call_success(self) -> None:
        session = AsyncMock()
        session.call_tool.return_value = _make_call_result("hello world")
        toolkit = _make_toolkit(session=session)

        tools = toolkit.get_tools()
        result = await tools[0].call(arg1="test")
        assert result == "hello world"
        session.call_tool.assert_called_once_with("test_tool", arguments={"arg1": "test"})

    @pytest.mark.asyncio
    async def test_call_error_flag(self) -> None:
        session = AsyncMock()
        session.call_tool.return_value = _make_call_result("bad input", is_error=True)
        toolkit = _make_toolkit(session=session)

        tools = toolkit.get_tools()
        result = await tools[0].call(arg1="x")
        assert result.startswith("Error: ")
        assert "bad input" in result

    @pytest.mark.asyncio
    async def test_call_exception(self) -> None:
        session = AsyncMock()
        session.call_tool.side_effect = ConnectionError("server died")
        toolkit = _make_toolkit(session=session)

        tools = toolkit.get_tools()
        result = await tools[0].call(arg1="x")
        assert "MCP tool error" in result
        assert "server died" in result

    @pytest.mark.asyncio
    async def test_multiple_content_blocks(self) -> None:
        block1 = MagicMock()
        block1.text = "line 1"
        block2 = MagicMock()
        block2.text = "line 2"
        call_result = MagicMock()
        call_result.content = [block1, block2]
        call_result.isError = False

        session = AsyncMock()
        session.call_tool.return_value = call_result
        toolkit = _make_toolkit(session=session)

        tools = toolkit.get_tools()
        result = await tools[0].call()
        assert "line 1" in result
        assert "line 2" in result

    @pytest.mark.asyncio
    async def test_non_text_content(self) -> None:
        block = MagicMock(spec=[])
        del block.text
        call_result = MagicMock()
        call_result.content = [block]
        call_result.isError = False

        session = AsyncMock()
        session.call_tool.return_value = call_result
        toolkit = _make_toolkit(session=session)

        tools = toolkit.get_tools()
        result = await tools[0].call()
        assert "[MagicMock]" in result


class TestMCPToolkitLifecycle:
    @pytest.mark.asyncio
    async def test_close(self) -> None:
        stack = AsyncExitStack()
        toolkit = MCPToolkit(
            session=AsyncMock(),
            context_stack=stack,
            mcp_tools=[],
            server_name="test",
        )
        await toolkit.close()
        await toolkit.close()  # idempotent

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        stack = AsyncExitStack()
        toolkit = MCPToolkit(
            session=AsyncMock(),
            context_stack=stack,
            mcp_tools=[_make_mcp_tool()],
            server_name="test",
        )
        async with toolkit as tk:
            assert tk.tool_count == 1
