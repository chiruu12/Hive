"""Bridge adapter for integrating the new runtime with the existing daemon."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from hive.runtime.types import Task, TaskStatus

if TYPE_CHECKING:
    from hive.runtime.agent import Agent


@dataclass
class GoalOutcome:
    """Result of an agent pursuing a goal. Used by the daemon loop."""

    steps_done: int = 0
    steps_failed: int = 0
    success: bool = False
    summary: str = ""
    results: list[Any] = field(default_factory=list)
    # Set when the run paused for human approval. The daemon parks the agent
    # (status WAITING) and leaves the goal active instead of completing/abandoning.
    waiting_approval: bool = False
    approval_ids: list[str] = field(default_factory=list)


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

        if result.status == TaskStatus.WAITING_APPROVAL:
            approval_ids = result.output.replace("Awaiting human approval:", "").strip()
            return GoalOutcome(
                steps_done=result.tool_calls_made or result.steps_taken,
                steps_failed=0,
                success=False,
                summary=result.output[:500] if result.output else str(result.status),
                waiting_approval=True,
                approval_ids=[a.strip() for a in approval_ids.split(",") if a.strip()],
            )

        return GoalOutcome(
            steps_done=result.tool_calls_made or result.steps_taken,
            steps_failed=1 if result.status == TaskStatus.FAILED else 0,
            success=result.status == TaskStatus.COMPLETED,
            summary=result.output[:500] if result.output else str(result.status),
        )
