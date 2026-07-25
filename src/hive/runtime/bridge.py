"""Bridge adapter for integrating the new runtime with the existing daemon."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from hive.memory.pursuit_transcript import messages_match
from hive.runtime.types import Task, TaskStatus

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from hive.memory.pursuit_transcript import PursuitTranscriptStore
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
    # Set when the ReAct loop stopped because profile/task max_steps was reached.
    hit_step_limit: bool = False
    # Cost tracking — populated from Agent's internal counters.
    cost_usd: float = 0.0
    tokens: int = 0


class DaemonAgentAdapter:
    """Makes a runtime Agent compatible with the daemon's pursue_goal() interface."""

    def __init__(self, agent: Agent, agent_id: str):
        self._agent = agent
        self._agent_id = agent_id

    async def pursue_goal(
        self,
        goal: str,
        context: str = "",
        *,
        goal_id: str = "",
        resume: bool = True,
        transcript_store: PursuitTranscriptStore | None = None,
    ) -> GoalOutcome:
        prior = []
        prior_len = 0
        if resume and transcript_store is not None and goal_id:
            prior = await transcript_store.load_messages(goal_id, self._agent_id)
            prior_len = len(prior)

        resume_cap = transcript_store.max_messages if transcript_store is not None else None

        if prior:
            task = Task(instruction=goal, max_steps=self._agent._max_steps)
            result = await self._agent.run(
                task,
                resume_messages=prior,
                continuation_context=context,
                conversation_max_messages=resume_cap,
            )
        else:
            instruction = goal
            if context:
                instruction = f"{goal}\n\nContext:\n{context}"
            task = Task(instruction=instruction, max_steps=self._agent._max_steps)
            result = await self._agent.run(task)

        if transcript_store is not None and goal_id and resume:
            messages = self._agent.last_conversation_messages
            if messages:
                if prior_len:
                    can_append_delta = len(messages) > prior_len and messages_match(
                        messages[:prior_len], prior
                    )
                    if can_append_delta:
                        new_messages = messages[prior_len:]
                        if new_messages:
                            await transcript_store.append_messages(
                                goal_id,
                                self._agent_id,
                                new_messages,
                            )
                    elif messages_match(messages, prior):
                        pass
                    else:
                        logger.warning(
                            "Rewriting pursuit transcript for goal %s: in-memory "
                            "conversation truncated or realigned (%d msgs vs %d archived); "
                            "persisting full snapshot",
                            goal_id,
                            len(messages),
                            prior_len,
                        )
                        await transcript_store.save_messages(goal_id, self._agent_id, messages)
                else:
                    await transcript_store.save_messages(goal_id, self._agent_id, messages)

        cost = self._agent._total_cost
        tokens = self._agent._total_tokens
        steps_done = result.tool_calls_made or result.steps_taken

        if result.status == TaskStatus.WAITING_APPROVAL:
            return GoalOutcome(
                steps_done=steps_done,
                steps_failed=0,
                success=False,
                summary=result.output[:500] if result.output else str(result.status),
                waiting_approval=True,
                approval_ids=list(result.approval_ids),
                cost_usd=cost,
                tokens=tokens,
            )

        if result.status == TaskStatus.MAX_STEPS:
            return GoalOutcome(
                steps_done=steps_done,
                steps_failed=0,
                success=False,
                hit_step_limit=True,
                summary=result.output[:500] if result.output else str(result.status),
                cost_usd=cost,
                tokens=tokens,
            )

        return GoalOutcome(
            steps_done=steps_done,
            steps_failed=1 if result.status == TaskStatus.FAILED else 0,
            success=result.status == TaskStatus.COMPLETED,
            summary=result.output[:500] if result.output else str(result.status),
            cost_usd=cost,
            tokens=tokens,
        )
