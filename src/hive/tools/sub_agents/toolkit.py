"""Sub-agent spawning and lifecycle management."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from hive.agents.state import AgentState, AgentStatus
from hive.memory.store import HiveStore
from hive.tools.base import Toolkit, tool

if TYPE_CHECKING:
    from hive.tools.notepad import NotepadManager

logger = logging.getLogger(__name__)

MAX_DEPTH = 2
MAX_CHILDREN = 5


class SubAgentManager:
    """Lifecycle management for sub-agents."""

    def __init__(self, store: HiveStore, hive_dir: Path):
        self._store = store
        self._hive_dir = hive_dir

    async def get_depth(self, agent_id: str) -> int:
        """Walk the spawned_by chain to determine nesting depth."""
        depth = 0
        current = agent_id
        for _ in range(MAX_DEPTH + 2):
            agent = await self._store.get_agent(current)
            if not agent or not agent.spawned_by:
                break
            depth += 1
            current = agent.spawned_by
        return depth

    async def check_limits(self, parent_agent_id: str) -> str | None:
        """Return error string if limits exceeded, None if OK."""
        parent_depth = await self.get_depth(parent_agent_id)
        if parent_depth >= MAX_DEPTH:
            return (
                f"Max nesting depth ({MAX_DEPTH}) reached. "
                "Cannot spawn deeper sub-agents."
            )
        children = await self._store.list_sub_agents(parent_agent_id)
        active = [c for c in children if c["status"] == "running"]
        if len(active) >= MAX_CHILDREN:
            return (
                f"Max active children ({MAX_CHILDREN}) reached. "
                "Terminate a sub-agent first."
            )
        return None

    async def spawn(
        self,
        parent_agent_id: str,
        name: str,
        role: str,
        task: str,
        model: str = "",
        max_cycles: int = 10,
    ) -> AgentState:
        """Spawn a sub-agent for the given parent."""
        error = await self.check_limits(parent_agent_id)
        if error:
            raise ValueError(error)

        parent = await self._store.get_agent(parent_agent_id)
        if not model and parent:
            model = parent.model

        agent_id = f"sub-{name}-{uuid4().hex[:8]}"
        depth = await self.get_depth(parent_agent_id) + 1
        workspace = str(self._hive_dir / "workspaces" / agent_id)

        state = AgentState(
            agent_id=agent_id,
            name=name,
            role=role,
            model=model,
            status=AgentStatus.IDLE,
            workspace=workspace,
            spawned_by=parent_agent_id,
            max_cycles=max_cycles,
            cycles_lived=0,
        )
        await self._store.save_agent(state)
        await self._store.save_sub_agent(
            sub_agent_id=agent_id,
            parent_agent_id=parent_agent_id,
            task=task,
            depth=depth,
            max_cycles=max_cycles,
        )
        logger.info(
            "Spawned sub-agent %s for parent %s (depth=%d, max_cycles=%d)",
            agent_id, parent_agent_id, depth, max_cycles,
        )
        return state

    async def terminate(
        self, sub_agent_id: str, parent_agent_id: str
    ) -> str:
        """Force-kill a sub-agent."""
        sub = await self._store.get_sub_agent(sub_agent_id)
        if not sub:
            return f"Sub-agent {sub_agent_id} not found."
        if sub["parent_agent_id"] != parent_agent_id:
            return "You can only terminate your own sub-agents."
        await self._store.update_agent_status(
            sub_agent_id, AgentStatus.DEAD
        )
        await self._store.complete_sub_agent(
            sub_agent_id, "Terminated by parent."
        )
        return f"Sub-agent {sub_agent_id} terminated."

    async def get_result(self, sub_agent_id: str) -> str | None:
        sub = await self._store.get_sub_agent(sub_agent_id)
        if not sub:
            return None
        return sub.get("result", "")

    async def auto_kill_expired(self) -> list[str]:
        """Kill sub-agents that exceeded max_cycles."""
        killed: list[str] = []
        agents = await self._store.list_agents()
        for agent in agents:
            if (
                agent.is_alive()
                and agent.spawned_by
                and agent.max_cycles
                and agent.cycles_lived >= agent.max_cycles
            ):
                await self._store.update_agent_status(
                    agent.agent_id, AgentStatus.DEAD
                )
                await self._store.complete_sub_agent(
                    agent.agent_id,
                    f"Auto-killed after {agent.cycles_lived} cycles.",
                )
                killed.append(agent.agent_id)
                logger.info(
                    "Auto-killed sub-agent %s (lived %d/%d cycles)",
                    agent.agent_id, agent.cycles_lived, agent.max_cycles,
                )
        return killed


class SubAgentToolkit(Toolkit):
    """Tools for spawning and managing sub-agents."""

    def __init__(
        self,
        manager: SubAgentManager,
        store: HiveStore,
        agent_id: str = "",
        notepad_manager: NotepadManager | None = None,
    ):
        self._manager = manager
        self._agent_id = agent_id
        self._store = store
        self._notepad = notepad_manager

    @tool()
    async def spawn_sub_agent(
        self,
        name: str,
        role: str,
        task: str,
        max_cycles: int = 10,
    ) -> str:
        """Spawn a sub-agent to handle a subtask. Returns sub-agent ID."""
        try:
            state = await self._manager.spawn(
                parent_agent_id=self._agent_id,
                name=name,
                role=role,
                task=task,
                max_cycles=max_cycles,
            )
            # Create a goal for the sub-agent
            goal_id = f"goal-{uuid4().hex[:8]}"
            await self._store.save_goal(goal_id, state.agent_id, task)
            return json.dumps({
                "sub_agent_id": state.agent_id,
                "status": "spawned",
                "max_cycles": max_cycles,
            })
        except ValueError as e:
            return json.dumps({"error": str(e)})

    @tool()
    async def list_sub_agents(self) -> str:
        """List all your spawned sub-agents and their status."""
        children = await self._store.list_sub_agents(self._agent_id)
        if not children:
            return "No sub-agents spawned."
        lines = []
        for c in children:
            agent = await self._store.get_agent(c["sub_agent_id"])
            status = agent.status.value if agent else c["status"]
            goal = await self._store.get_active_goal(c["sub_agent_id"])
            goal_text = goal["objective"][:60] if goal else "-"
            lines.append(
                f"- {c['sub_agent_id']}: status={status}, "
                f"task={c['task'][:60]}, goal={goal_text}"
            )
        return "\n".join(lines)

    @tool()
    async def get_sub_agent_status(self, sub_agent_id: str) -> str:
        """Get detailed status of a sub-agent."""
        sub = await self._store.get_sub_agent(sub_agent_id)
        if not sub:
            return f"Sub-agent {sub_agent_id} not found."
        agent = await self._store.get_agent(sub_agent_id)
        if not agent:
            return f"Agent record missing for {sub_agent_id}."
        goal = await self._store.get_active_goal(sub_agent_id)
        return json.dumps({
            "id": sub_agent_id,
            "status": agent.status.value,
            "task": sub["task"],
            "cycles_lived": agent.cycles_lived,
            "max_cycles": sub["max_cycles"],
            "current_goal": goal["objective"] if goal else None,
            "result": sub.get("result", ""),
        })

    @tool()
    async def read_sub_agent_journal(self, sub_agent_id: str) -> str:
        """Read a sub-agent's notepad to see its thinking."""
        if self._notepad:
            return self._notepad.read(sub_agent_id)
        return "Journal system not available."

    @tool()
    async def send_instruction(self, sub_agent_id: str, instruction: str) -> str:
        """Send a direction/instruction to a sub-agent."""
        sub = await self._store.get_sub_agent(sub_agent_id)
        if not sub:
            return f"Sub-agent {sub_agent_id} not found."
        if sub["parent_agent_id"] != self._agent_id:
            return "You can only instruct your own sub-agents."
        nudge_id = f"nudge-{uuid4().hex[:8]}"
        await self._store.save_nudge(nudge_id, sub_agent_id, instruction)
        return f"Instruction sent to {sub_agent_id}."

    @tool()
    async def get_sub_agent_result(self, sub_agent_id: str) -> str:
        """Get the final result/output from a completed sub-agent."""
        result = await self._manager.get_result(sub_agent_id)
        if result is None:
            return f"Sub-agent {sub_agent_id} not found."
        if not result:
            return f"Sub-agent {sub_agent_id} has no result yet."
        return result

    @tool()
    async def terminate_sub_agent(self, sub_agent_id: str) -> str:
        """Force-kill a sub-agent."""
        return await self._manager.terminate(sub_agent_id, self._agent_id)
