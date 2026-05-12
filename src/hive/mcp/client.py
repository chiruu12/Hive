"""MCP client — connect to any MCP server and use its tools as a Hive Toolkit."""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from hive.runtime.tools import Tool, Toolkit

logger = logging.getLogger(__name__)


class MCPToolkit(Toolkit):
    """Toolkit that wraps an MCP server's tools as Hive Tools.

    Usage:
        toolkit = await MCPToolkit.from_stdio(
            "npx", ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        )
        agent = Agent(name="fs", model=provider, toolkits=[toolkit])
        result = await agent.run(Task(instruction="List files in /tmp"))
        await toolkit.close()

    Or as a context manager:
        async with await MCPToolkit.from_stdio("npx", [...]) as toolkit:
            agent = Agent(name="fs", model=provider, toolkits=[toolkit])
            ...
    """

    def __init__(
        self,
        session: Any,
        context_stack: AsyncExitStack,
        mcp_tools: list[Any],
        server_name: str = "",
    ) -> None:
        self._session = session
        self._stack = context_stack
        self._mcp_tools = mcp_tools
        self._server_name = server_name
        self._closed = False

    @classmethod
    async def from_stdio(
        cls,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | Path | None = None,
    ) -> MCPToolkit:
        """Connect to an MCP server via stdio transport."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        stack = AsyncExitStack()
        server_params = StdioServerParameters(
            command=command,
            args=args or [],
            env=env,
            cwd=str(cwd) if cwd else None,
        )

        read, write = await stack.enter_async_context(stdio_client(server_params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        tools_result = await session.list_tools()

        logger.info(
            "MCP connected: %s (%d tools)", command, len(tools_result.tools)
        )

        return cls(
            session=session,
            context_stack=stack,
            mcp_tools=tools_result.tools,
            server_name=command,
        )

    @classmethod
    async def from_config(cls, config: dict[str, Any]) -> MCPToolkit:
        """Connect from a config dict: {"command": "...", "args": [...], "env": {...}}."""
        return await cls.from_stdio(
            command=config["command"],
            args=config.get("args"),
            env=config.get("env"),
            cwd=config.get("cwd"),
        )

    def get_tools(self) -> list[Tool]:
        """Convert MCP tools to Hive Tool objects."""
        hive_tools: list[Tool] = []
        for mcp_tool in self._mcp_tools:
            hive_tools.append(
                Tool(
                    name=mcp_tool.name,
                    description=mcp_tool.description or "(no description)",
                    parameters=mcp_tool.inputSchema or {"type": "object", "properties": {}},
                    fn=self._make_call_fn(mcp_tool.name),
                    is_async=True,
                )
            )
        return hive_tools

    def _make_call_fn(self, tool_name: str) -> Any:
        """Create an async callable that invokes the MCP tool."""
        session = self._session

        async def call_mcp_tool(**kwargs: Any) -> str:
            try:
                result = await session.call_tool(tool_name, arguments=kwargs)
                texts: list[str] = []
                for content_block in result.content:
                    if hasattr(content_block, "text"):
                        texts.append(content_block.text)
                    else:
                        texts.append(f"[{type(content_block).__name__}]")
                output = "\n".join(texts)
                if result.isError:
                    return f"Error: {output}"
                return output
            except Exception as e:
                return f"MCP tool error: {e}"

        return call_mcp_tool

    @property
    def tool_count(self) -> int:
        return len(self._mcp_tools)

    @property
    def server_name(self) -> str:
        return self._server_name

    async def close(self) -> None:
        """Close the MCP server connection and kill the subprocess."""
        if not self._closed:
            self._closed = True
            await self._stack.aclose()
            logger.info("MCP disconnected: %s", self._server_name)

    async def __aenter__(self) -> MCPToolkit:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
