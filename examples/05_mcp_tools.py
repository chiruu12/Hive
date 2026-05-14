"""MCP Tools — connect to any MCP server and use its tools.

This example connects to a filesystem MCP server and gives
the agent real filesystem access through the MCP protocol.

Requires: npx (Node.js) installed for the MCP server.

Run: uv run python examples/05_mcp_tools.py
"""

import asyncio

from hive import Agent, MCPToolkit, Task, create_runtime_provider


async def main() -> None:
    provider = create_runtime_provider("claude-haiku-4-5")

    print("Connecting to filesystem MCP server...")
    async with await MCPToolkit.from_stdio(
        "npx",
        ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/hive-mcp-demo"],
    ) as mcp:
        print(f"Connected! {mcp.tool_count} tools available:")
        for t in mcp.get_tools():
            print(f"  - {t.name}: {t.description[:60]}")

        agent = Agent(
            name="explorer",
            model=provider,
            system_prompt="You explore filesystems and report what you find.",
            toolkits=[mcp],
            max_steps=10,
        )

        result = await agent.run(
            Task(instruction="Create a file called notes.txt with today's date, then list the directory.")
        )

        print(f"\nStatus: {result.status}")
        print(f"Tool calls: {result.tool_calls_made}")
        print(f"\nOutput:\n{result.output}")


if __name__ == "__main__":
    asyncio.run(main())
