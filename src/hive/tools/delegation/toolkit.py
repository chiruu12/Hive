"""Delegation toolkits — daemon-level and runtime-level delegation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from hive.runtime.types import Task
from hive.tools.base import Toolkit, tool

if TYPE_CHECKING:
    from hive.agents.delegation import DelegationEngine
    from hive.memory.store import HiveStore
    from hive.runtime.agent import Agent

logger = logging.getLogger(__name__)


class DaemonDelegationToolkit(Toolkit):
    """Delegation tools for daemon agents to coordinate with peers."""

    def __init__(
        self,
        delegation_engine: DelegationEngine,
        store: HiveStore,
        agent_id: str = "",
    ):
        self._engine = delegation_engine
        self._agent_id = agent_id
        self._store = store

    @tool()
    async def delegate_task(
        self,
        agent_name: str,
        objective: str,
    ) -> str:
        """Delegate a task to another agent in the hive.

        Args:
            agent_name: Name or ID of the target agent.
            objective: What you want the agent to accomplish.
        """
        agents = await self._store.list_agents()
        target = None
        for a in agents:
            if a.agent_id == self._agent_id:
                continue
            if not a.is_alive():
                continue
            if (
                a.name == agent_name
                or a.agent_id == agent_name
                or a.agent_id.startswith(agent_name)
            ):
                target = a
                break
        if not target:
            alive = [a for a in agents if a.is_alive() and a.agent_id != self._agent_id]
            names = ", ".join(a.name for a in alive)
            return f"Agent not found: {agent_name}. Available: {names}"

        record = await self._engine.delegate(
            self._agent_id,
            target.agent_id,
            objective,
        )
        return (
            f"Delegated to {target.name} "
            f"(id={record.delegation_id}). "
            f"Goal '{objective}' created in their queue."
        )

    @tool()
    async def check_delegation(self, delegation_id: str) -> str:
        """Check the status of a previously delegated task.

        Args:
            delegation_id: The ID returned from delegate_task.
        """
        record = await self._engine.check_completion(delegation_id)
        if not record:
            return f"Delegation not found: {delegation_id}"
        return f"Status: {record.status}. Result: {record.result or 'pending'}"

    @tool()
    async def list_peers(self) -> str:
        """List all alive agents you can delegate to."""
        agents = await self._store.list_agents()
        alive = [a for a in agents if a.is_alive() and a.agent_id != self._agent_id]
        if not alive:
            return "No other agents available."
        lines = []
        for a in alive:
            goal = await self._store.get_active_goal(a.agent_id)
            if goal:
                status = f"working on: {goal['objective'][:50]}"
            else:
                status = "idle"
            lines.append(f"- {a.name} ({a.role}): {status}")
        return "Available peers:\n" + "\n".join(lines)


class DelegationToolkit(Toolkit):
    """Lets an agent delegate subtasks to other agents.

    Usage:
        agents = {"researcher": researcher_agent, "coder": coder_agent}
        toolkit = DelegationToolkit(agents)
        leader = Agent(name="lead", model=provider, toolkits=[toolkit])
    """

    def __init__(self, agents: dict[str, Agent]):
        self._agents = agents

    @tool()
    async def delegate_task(self, agent_name: str, task: str) -> str:
        """Delegate a task to another agent and get their result.

        Args:
            agent_name: Name of the agent to delegate to.
            task: Description of what the agent should do.
        """
        target = self._agents.get(agent_name)
        if not target:
            available = ", ".join(self._agents.keys())
            return f"Error: agent '{agent_name}' not found. Available: {available}"

        logger.info("Delegating to %s: %s", agent_name, task[:100])
        try:
            result = await target.run(Task(instruction=task))
            status = "completed" if result.status == "completed" else str(result.status)
            return (
                f"[{agent_name}] Status: {status}\n"
                f"Steps: {result.steps_taken}, Tools: {result.tool_calls_made}\n"
                f"Output: {result.output[:2000]}"
            )
        except Exception as e:
            return f"Error delegating to {agent_name}: {e}"

    @tool()
    def list_agents(self) -> str:
        """List all available agents you can delegate to.

        Returns their names.
        """
        if not self._agents:
            return "No agents available for delegation."
        lines = [f"- {name}" for name in self._agents]
        return "Available agents:\n" + "\n".join(lines)
