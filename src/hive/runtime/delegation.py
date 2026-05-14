"""Delegation toolkit — agents delegate tasks to other agents via tool calls."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from hive.runtime.tools import Toolkit, tool
from hive.runtime.types import Task

if TYPE_CHECKING:
    from hive.runtime.agent import Agent

logger = logging.getLogger(__name__)


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
