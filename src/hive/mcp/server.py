"""MCP server — expose Hive as tools for Claude Code and other MCP clients."""

import asyncio
import json
import logging
import sys
from pathlib import Path
from uuid import uuid4

from hive.agents.profile import AgentProfile, default_profiles_dir
from hive.agents.state import AgentState, AgentStatus
from hive.memory.store import HiveStore

logger = logging.getLogger(__name__)


class HiveMCPServer:
    """Stdio-based MCP server that exposes Hive operations as tools."""

    def __init__(self, hive_dir: Path | None = None):
        self._hive_dir = hive_dir or Path.cwd() / ".hive"
        self._store = HiveStore(self._hive_dir / "hive.db")
        self._daemon_task: asyncio.Task | None = None
        self._request_id = 0

    def _tools(self) -> list[dict]:
        return [
            {
                "name": "hive_init",
                "description": "Initialize a new hive in the current directory",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "hive_start",
                "description": "Start the hive daemon with agents",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "profiles": {
                            "type": "string",
                            "description": "Comma-separated profile names (default: coder)",
                        },
                        "heartbeat": {
                            "type": "integer",
                            "description": "Seconds between cycles (default: 15)",
                        },
                    },
                },
            },
            {
                "name": "hive_stop",
                "description": "Stop the running hive daemon",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "hive_status",
                "description": "Show all agents, their goals, and suffering levels",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "hive_spawn",
                "description": "Add a new agent to the running hive",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "profile": {
                            "type": "string",
                            "description": "Profile name (coder, researcher, reviewer, tester)",
                        },
                    },
                    "required": ["profile"],
                },
            },
            {
                "name": "hive_kill",
                "description": "Remove an agent from the hive",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent": {
                            "type": "string",
                            "description": "Agent name or ID",
                        },
                    },
                    "required": ["agent"],
                },
            },
            {
                "name": "hive_nudge",
                "description": "Give direction to an agent",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent": {"type": "string", "description": "Agent name or ID"},
                        "message": {"type": "string", "description": "Direction to give"},
                    },
                    "required": ["agent", "message"],
                },
            },
            {
                "name": "hive_logs",
                "description": "Get recent events for an agent",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent": {"type": "string", "description": "Agent name or ID"},
                        "limit": {"type": "integer", "description": "Max events (default: 20)"},
                    },
                    "required": ["agent"],
                },
            },
            {
                "name": "hive_models",
                "description": "List available model providers and their status",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]

    async def handle_tool(self, name: str, args: dict) -> str:
        """Execute a tool and return the result as text."""
        if name == "hive_init":
            return await self._init()
        if name == "hive_start":
            return await self._start(
                args.get("profiles", "coder"),
                args.get("heartbeat", 15),
            )
        if name == "hive_stop":
            return await self._stop()
        if name == "hive_status":
            return await self._status()
        if name == "hive_spawn":
            return await self._spawn(args["profile"])
        if name == "hive_kill":
            return await self._kill(args["agent"])
        if name == "hive_nudge":
            return await self._nudge(args["agent"], args["message"])
        if name == "hive_logs":
            return await self._logs(args["agent"], args.get("limit", 20))
        if name == "hive_models":
            return await self._models()
        return f"Unknown tool: {name}"

    async def _init(self) -> str:
        from hive.daemon.setup import initialize_hive

        if self._hive_dir.exists():
            return "Hive already initialized."
        initialize_hive(self._hive_dir.parent)
        return "Hive initialized. Use hive_start to bring agents alive."

    async def _start(self, profiles_str: str, heartbeat: int) -> str:
        if self._daemon_task and not self._daemon_task.done():
            return "Daemon is already running."

        from hive.daemon.loop import HiveDaemon

        if not self._hive_dir.exists():
            from hive.daemon.setup import initialize_hive

            initialize_hive(self._hive_dir.parent)

        await self._store.initialize()
        profiles_dir = default_profiles_dir()
        profile_names = [p.strip() for p in profiles_str.split(",")]
        spawned = []

        for name in profile_names:
            try:
                profile = AgentProfile.from_preset(name, profiles_dir)
                agent_id = f"{profile.name}-{uuid4().hex[:8]}"
                state = AgentState(
                    agent_id=agent_id,
                    name=profile.name,
                    role=profile.role,
                    model=profile.model,
                    status=AgentStatus.IDLE,
                    workspace=str(self._hive_dir / "workspaces" / agent_id),
                )
                await self._store.save_agent(state)
                spawned.append(f"{name} ({agent_id[:16]})")
            except FileNotFoundError:
                spawned.append(f"{name} (profile not found)")

        daemon = HiveDaemon(
            self._hive_dir,
            heartbeat=heartbeat,
            logs_dir=self._hive_dir.parent / "logs",
            profiles=profile_names,
        )
        self._daemon_task = asyncio.create_task(daemon.start())

        return f"Hive started. Heartbeat: {heartbeat}s. Agents: {', '.join(spawned)}"

    async def _stop(self) -> str:
        if self._daemon_task and not self._daemon_task.done():
            self._daemon_task.cancel()
            self._daemon_task = None
            return "Daemon stopped."
        return "No daemon running."

    async def _status(self) -> str:
        try:
            await self._store.initialize()
            agents = await self._store.list_agents()
        except Exception:
            return "No hive initialized. Use hive_init first."

        if not agents:
            return "No agents. Use hive_start to bring them alive."

        lines = []
        for a in agents:
            goal = await self._store.get_active_goal(a.agent_id)
            goal_text = goal["objective"][:60] if goal else "idle"
            status = a.status.value if hasattr(a.status, "value") else a.status
            lines.append(f"  {a.name} [{status}] model={a.model} goal={goal_text}")
        return "Agents:\n" + "\n".join(lines)

    async def _spawn(self, profile_name: str) -> str:
        profiles_dir = default_profiles_dir()
        try:
            profile = AgentProfile.from_preset(profile_name, profiles_dir)
        except FileNotFoundError:
            return f"Profile not found: {profile_name}"

        agent_id = f"{profile.name}-{uuid4().hex[:8]}"
        state = AgentState(
            agent_id=agent_id,
            name=profile.name,
            role=profile.role,
            model=profile.model,
            status=AgentStatus.IDLE,
            workspace=str(self._hive_dir / "workspaces" / agent_id),
        )
        await self._store.initialize()
        await self._store.save_agent(state)
        return f"Spawned {profile.name} ({agent_id})"

    async def _kill(self, agent_ref: str) -> str:
        await self._store.initialize()
        agents = await self._store.list_agents()
        target = None
        for a in agents:
            if a.agent_id == agent_ref or a.name == agent_ref or a.agent_id.startswith(agent_ref):
                target = a
                break
        if not target:
            return f"Agent not found: {agent_ref}"
        await self._store.update_agent_status(target.agent_id, AgentStatus.DEAD)
        return f"Killed {target.name} ({target.agent_id})"

    async def _nudge(self, agent_ref: str, message: str) -> str:
        await self._store.initialize()
        agents = await self._store.list_agents()
        target = None
        for a in agents:
            if a.agent_id == agent_ref or a.name == agent_ref or a.agent_id.startswith(agent_ref):
                target = a
                break
        if not target:
            return f"Agent not found: {agent_ref}"
        nudge_id = f"nudge-{uuid4().hex[:8]}"
        await self._store.save_nudge(nudge_id, target.agent_id, message)
        return f"Nudged {target.name}: {message}"

    async def _logs(self, agent_ref: str, limit: int) -> str:
        from hive.memory.events import EventLog

        event_log = EventLog(self._hive_dir)
        await self._store.initialize()
        agents = await self._store.list_agents()
        target = None
        for a in agents:
            if a.agent_id == agent_ref or a.name == agent_ref or a.agent_id.startswith(agent_ref):
                target = a
                break
        if not target:
            return f"Agent not found: {agent_ref}"

        sessions = await event_log.list_sessions(target.agent_id)
        if not sessions:
            return f"No events for {target.name}"

        latest = sessions[-1]
        events = await event_log.replay(target.agent_id, latest)
        lines = []
        for e in events[-limit:]:
            ts = e.ts.strftime("%H:%M:%S")
            lines.append(f"  [{ts}] {e.event_type}: {json.dumps(e.data)[:100]}")
        return f"Events for {target.name} (session {latest}):\n" + "\n".join(lines)

    async def _models(self) -> str:
        from hive.models.router import detect_models

        models = detect_models()
        lines = []
        for provider, model_list in models.items():
            avail = sum(1 for m in model_list if m.available)
            lines.append(f"  {provider}: {len(model_list)} models ({avail} available)")
            for m in model_list:
                status = "✓" if m.available else "✗"
                lines.append(f"    {status} {m.name}")
        return "Model Providers:\n" + "\n".join(lines)

    async def run_stdio(self) -> None:
        """Run as MCP server on stdin/stdout."""
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout
        )
        writer = asyncio.StreamWriter(
            writer_transport, writer_protocol, None, asyncio.get_event_loop()
        )

        await self._send(
            writer,
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )

        while True:
            line = await reader.readline()
            if not line:
                break

            try:
                msg = json.loads(line.decode())
            except json.JSONDecodeError:
                continue

            response = await self._handle_message(msg)
            if response:
                await self._send(writer, response)

    async def _handle_message(self, msg: dict) -> dict | None:
        method = msg.get("method", "")
        req_id = msg.get("id")

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "hive", "version": "0.1.0"},
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self._tools()},
            }

        if method == "tools/call":
            params = msg.get("params", {})
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})

            try:
                result = await self.handle_tool(tool_name, tool_args)
            except Exception as e:
                result = f"Error: {e}"

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": result}],
                },
            }

        return None

    async def _send(self, writer: asyncio.StreamWriter, msg: dict) -> None:
        data = json.dumps(msg) + "\n"
        writer.write(data.encode())
        await writer.drain()


def main() -> None:
    """Entry point for `hive-mcp` command."""
    server = HiveMCPServer()
    asyncio.run(server.run_stdio())
