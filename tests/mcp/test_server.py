"""Tests for the Hive MCP server protocol + tool dispatch (F1 coverage).

Drives HiveMCPServer message handling directly -- no stdio transport.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hive.mcp.server import HiveMCPServer


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> HiveMCPServer:
    # Run in an isolated cwd with its own profiles/ so the spawn path resolves
    # `default_profiles_dir()` deterministically (it checks Path.cwd()/profiles
    # first) instead of depending on the ambient working directory.
    monkeypatch.chdir(tmp_path)
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "coder.yaml").write_text(
        'name: coder\nrole: "Test agent"\nmodel: claude-haiku-4-5\nautonomy: high\nmax_steps: 5\n'
    )
    hive_dir = tmp_path / ".hive"
    hive_dir.mkdir(parents=True)  # so the store's hive.db parent exists
    return HiveMCPServer(hive_dir=hive_dir)


class TestProtocol:
    async def test_initialize_returns_capabilities(self, server: HiveMCPServer) -> None:
        resp = await server._handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert resp is not None
        assert resp["id"] == 1
        assert resp["result"]["protocolVersion"]
        assert "tools" in resp["result"]["capabilities"]
        assert resp["result"]["serverInfo"]["name"] == "hive"

    async def test_tools_list_exposes_all_tools(self, server: HiveMCPServer) -> None:
        resp = await server._handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert resp is not None
        names = {t["name"] for t in resp["result"]["tools"]}
        assert {"hive_init", "hive_start", "hive_status", "hive_spawn", "hive_models"} <= names
        # Every tool advertises an input schema.
        assert all("inputSchema" in t for t in resp["result"]["tools"])

    async def test_unknown_method_returns_none(self, server: HiveMCPServer) -> None:
        assert await server._handle_message({"id": 9, "method": "resources/list"}) is None


class TestToolsCall:
    async def test_status_on_empty_hive(self, server: HiveMCPServer) -> None:
        resp = await server._handle_message(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "hive_status", "arguments": {}},
            }
        )
        assert resp is not None
        text = resp["result"]["content"][0]["text"]
        assert "No agents" in text

    async def test_spawn_then_status(self, server: HiveMCPServer) -> None:
        spawn = await server._handle_message(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "hive_spawn", "arguments": {"profile": "coder"}},
            }
        )
        assert "Spawned" in spawn["result"]["content"][0]["text"]

        status = await server._handle_message(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "hive_status", "arguments": {}},
            }
        )
        assert "coder" in status["result"]["content"][0]["text"]

    async def test_missing_required_arg_is_caught(self, server: HiveMCPServer) -> None:
        """A KeyError from a missing required arg becomes an error result, not a crash."""
        resp = await server._handle_message(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {"name": "hive_spawn", "arguments": {}},  # missing "profile"
            }
        )
        assert resp["result"]["content"][0]["text"].startswith("Error:")


class TestHandleTool:
    async def test_unknown_tool(self, server: HiveMCPServer) -> None:
        assert await server.handle_tool("hive_teleport", {}) == "Unknown tool: hive_teleport"

    async def test_spawn_unknown_profile(self, server: HiveMCPServer) -> None:
        assert (await server.handle_tool("hive_spawn", {"profile": "ghost"})).startswith(
            "Profile not found"
        )

    async def test_kill_missing_agent(self, server: HiveMCPServer) -> None:
        assert (await server.handle_tool("hive_kill", {"agent": "nobody"})).startswith(
            "Agent not found"
        )
