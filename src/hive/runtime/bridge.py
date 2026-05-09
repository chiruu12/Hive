"""Bridge adapter for integrating the new runtime with the existing daemon."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from hive.runtime.types import Task

if TYPE_CHECKING:
    from hive.runtime.agent import Agent


@dataclass
class GoalOutcome:
    """Result of an agent pursuing a goal. Used by the daemon loop."""

    steps_done: int = 0
    steps_failed: int = 0
    success: bool = False
    summary: str = ""
    results: list = field(default_factory=list)


class DaemonAgentAdapter:
    """Makes a runtime Agent compatible with the daemon's pursue_goal() interface."""

    def __init__(self, agent: Agent, agent_id: str):
        self._agent = agent
        self._agent_id = agent_id

    async def pursue_goal(self, goal: str, context: str = "") -> GoalOutcome:
        instruction = goal
        if context:
            instruction = f"{goal}\n\nContext:\n{context}"

        task = Task(instruction=instruction)
        result = await self._agent.run(task)

        return GoalOutcome(
            steps_done=result.tool_calls_made or result.steps_taken,
            steps_failed=1 if result.status == "failed" else 0,
            success=result.status == "completed",
            summary=result.output[:500] if result.output else str(result.status),
        )
