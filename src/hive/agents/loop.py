"""Autonomy loop — plan-execute-substitute engine for goal pursuit."""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from hive.agents.base import AgentLoopBase
from hive.agents.profile import AgentProfile
from hive.config import get_config
from hive.execution.action import Action, ActionResult, parse_action_plan
from hive.execution.context import ExecutionContext
from hive.logging.models import DecisionLog, GoalLog, ToolLog
from hive.logging.writer import LogWriter
from hive.memory.events import EventLog, EventType
from hive.memory.store import HiveStore

logger = logging.getLogger(__name__)


def _max_retries() -> int:
    return get_config().daemon.max_retries


@dataclass
class GoalOutcome:
    steps_done: int = 0
    steps_failed: int = 0
    success: bool = False
    summary: str = ""
    results: list[ActionResult] = field(default_factory=list)


class AgentLoop(AgentLoopBase):
    """Drives one cycle of goal pursuit via plan-execute-substitute."""

    def __init__(
        self,
        agent_id: str,
        profile: AgentProfile,
        provider: Any,
        ctx: ExecutionContext,
        store: HiveStore,
        event_log: EventLog,
        log_writer: LogWriter | None = None,
        session_id: str = "",
        goal_id: str = "",
    ):
        super().__init__(agent_id, profile, provider, ctx, store, event_log, log_writer, session_id)
        self._goal_id = goal_id

    async def pursue_goal(self, goal: str, context: str = "") -> GoalOutcome:
        """Execute one cycle of goal pursuit."""
        outcome = GoalOutcome()

        actions = await self._get_plan(goal, context, decision_type="plan")
        if not actions:
            outcome.summary = "Failed to generate plan"
            return outcome

        if self._log:
            self._log.log_goal(
                GoalLog(
                    agent_id=self._agent_id,
                    goal_id=self._goal_id,
                    event="plan_created",
                    objective=goal,
                    plan=[a.model_dump() for a in actions],
                )
            )

        retries = 0

        for i, action in enumerate(actions):
            await self._emit(
                EventType.TOOL_USED,
                {
                    "tool": getattr(action, "tool_name", None) or action.type,
                    "params": action.model_dump(exclude={"type", "rationale"}),
                    "step": i,
                    "rationale": action.rationale,
                },
            )

            t0 = time.time()
            result = await action.execute(self._ctx, self._agent_id)
            action_ms = int((time.time() - t0) * 1000)
            outcome.results.append(result)

            if self._log:
                self._log.log_tool(
                    ToolLog(
                        agent_id=self._agent_id,
                        goal_id=self._goal_id,
                        step_index=i,
                        tool_name=result.action_name,
                        params_raw=action.model_dump(exclude={"type", "rationale"}),
                        params_resolved=action.model_dump(exclude={"type", "rationale"}),
                        success=result.success,
                        output=result.output,
                        duration_ms=action_ms,
                        artifacts=result.artifacts,
                    )
                )

            await self._emit(
                EventType.TOOL_RESULT,
                {
                    "tool": result.action_name,
                    "success": result.success,
                    "output": result.output[:500],
                },
            )

            if result.success:
                outcome.steps_done += 1
                retries = 0
            else:
                outcome.steps_failed += 1
                retries += 1
                if retries > _max_retries():
                    outcome.summary = f"Abandoned after {retries} retries on step {i}"
                    return outcome
                replan = await self._get_plan(
                    goal,
                    f"Step {i} failed: {result.output}. Replan from here.",
                    decision_type="replan",
                )
                if replan:
                    actions[i + 1 :] = replan

        outcome.success = outcome.steps_done > 0
        outcome.summary = f"Completed {outcome.steps_done}/{len(actions)} steps"
        return outcome

    async def _get_plan(
        self, goal: str, context: str = "", decision_type: str = "plan"
    ) -> list[Action]:
        """Ask Claude for a structured execution plan as Actions."""
        system = self._profile.build_system_prompt()

        available_actions = (
            "Available action types:\n"
            '- {"type": "tool", "tool_name": "<name>", "params": {...}, "rationale": "why"}\n'
            '- {"type": "world", "action": "work|apply_job|quit_job|learn|gamble", '
            '"target": "...", "rationale": "why"}\n'
            '- {"type": "memory", "operation": "set|get", "key": "...", '
            '"value": "...", "rationale": "why"}\n'
            '- {"type": "message", "target_agent": "...", "message": "...", "rationale": "why"}\n'
        )

        prompt = f"You are pursuing this goal: {goal}\n\n{available_actions}\n"
        if context:
            prompt += f"Context: {context}\n\n"
        prompt += "Output ONLY a JSON array of actions. No markdown, no explanation."

        response = await self._provider.complete(
            messages=[{"role": "user", "content": prompt}],
            system=system,
        )

        actions = parse_action_plan(response.content)

        if self._log:
            self._log.log_decision(
                DecisionLog(
                    agent_id=self._agent_id,
                    decision_type=decision_type,
                    model=response.model,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    cost_usd=response.cost_usd,
                    duration_ms=response.duration_ms,
                    response_raw=response.content,
                    response_parsed={"actions": [a.model_dump() for a in actions]}
                    if actions
                    else None,
                    success=bool(actions),
                )
            )

        return actions
