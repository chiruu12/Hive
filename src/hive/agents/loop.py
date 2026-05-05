"""Autonomy loop — plan-execute-substitute engine for goal pursuit."""

import json
import logging
import time
from dataclasses import dataclass, field

from hive.agents.profile import AgentProfile
from hive.execution.protocol import ToolResult
from hive.execution.registry import ToolRegistry
from hive.logging.models import DecisionLog, GoalLog, ToolLog
from hive.logging.writer import LogWriter
from hive.memory.events import EventLog, EventType, HiveEvent
from hive.memory.store import HiveStore
from hive.models.claude import ClaudeCLIProvider

logger = logging.getLogger(__name__)

MAX_RETRIES = 2


@dataclass
class GoalOutcome:
    steps_done: int = 0
    steps_failed: int = 0
    success: bool = False
    summary: str = ""
    tool_results: list[ToolResult] = field(default_factory=list)


class AgentLoop:
    """Drives one cycle of goal pursuit via plan-execute-substitute."""

    def __init__(
        self,
        agent_id: str,
        profile: AgentProfile,
        provider: ClaudeCLIProvider,
        registry: ToolRegistry,
        store: HiveStore,
        event_log: EventLog,
        log_writer: LogWriter | None = None,
        session_id: str = "",
        goal_id: str = "",
    ):
        self._agent_id = agent_id
        self._profile = profile
        self._provider = provider
        self._registry = registry
        self._store = store
        self._events = event_log
        self._log = log_writer
        self._session_id = session_id or f"sess-{agent_id}"
        self._goal_id = goal_id

    async def pursue_goal(self, goal: str, context: str = "") -> GoalOutcome:
        """Execute one cycle of goal pursuit."""
        outcome = GoalOutcome()

        tools_desc = self._registry.get_tool_schemas()
        plan = await self._get_plan(goal, tools_desc, context, decision_type="plan")

        if not plan:
            outcome.summary = "Failed to generate plan"
            return outcome

        if self._log:
            self._log.log_goal(
                GoalLog(
                    agent_id=self._agent_id,
                    goal_id=self._goal_id,
                    event="plan_created",
                    objective=goal,
                    plan=plan,
                )
            )

        prev_result = ""
        retries = 0

        for i, step in enumerate(plan):
            tool_name = step.get("tool", "")
            raw_params = step.get("params", {})
            resolved_params = self._substitute(raw_params, prev_result)

            await self._emit(
                EventType.TOOL_USED,
                {
                    "tool": tool_name,
                    "params": resolved_params,
                    "step": i,
                    "rationale": step.get("rationale", ""),
                },
            )

            t0 = time.time()
            result = await self._registry.execute(tool_name, self._agent_id, **resolved_params)
            tool_ms = int((time.time() - t0) * 1000)
            outcome.tool_results.append(result)

            if self._log:
                self._log.log_tool(
                    ToolLog(
                        agent_id=self._agent_id,
                        goal_id=self._goal_id,
                        step_index=i,
                        tool_name=tool_name,
                        params_raw=raw_params,
                        params_resolved=resolved_params,
                        success=result.success,
                        output=result.output,
                        error=result.error,
                        duration_ms=tool_ms,
                        artifacts=result.artifacts,
                    )
                )

            await self._emit(
                EventType.TOOL_RESULT,
                {
                    "tool": tool_name,
                    "success": result.success,
                    "output": result.output[:500],
                },
            )

            if result.success:
                prev_result = result.output
                outcome.steps_done += 1
                retries = 0
            else:
                outcome.steps_failed += 1
                retries += 1
                if retries > MAX_RETRIES:
                    outcome.summary = f"Abandoned after {retries} retries on step {i}"
                    return outcome
                replan = await self._get_plan(
                    goal,
                    tools_desc,
                    f"Step {i} failed: {result.output}. Replan from here.",
                    decision_type="replan",
                )
                if replan:
                    plan[i + 1 :] = replan
                    prev_result = f"Previous step failed: {result.output}"

        outcome.success = outcome.steps_done > 0
        outcome.summary = f"Completed {outcome.steps_done}/{len(plan)} steps"
        return outcome

    async def _get_plan(
        self, goal: str, tools_desc: str, context: str = "", decision_type: str = "plan"
    ) -> list[dict]:
        """Ask Claude for a structured execution plan."""
        system = self._profile.build_system_prompt()
        prompt = f"You are pursuing this goal: {goal}\n\nAvailable tools:\n{tools_desc}\n\n"
        if context:
            prompt += f"Context: {context}\n\n"
        prompt += (
            "Create a plan as a JSON array of steps. Each step:\n"
            '{"tool": "tool_name", "params": {"key": "value"}, "rationale": "why"}\n\n'
            "Use {{prev_result}} in params to reference the previous step's output.\n"
            "Output ONLY the JSON array. No markdown, no explanation."
        )

        response = await self._provider.complete(
            messages=[{"role": "user", "content": prompt}],
            system=system,
        )

        plan = self._parse_plan(response.content)

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
                    response_parsed={"steps": plan} if plan else None,
                    success=bool(plan),
                )
            )

        return plan

    def _parse_plan(self, text: str) -> list[dict]:
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            logger.warning("Failed to parse plan JSON: %s", text[:200])
        return []

    def _substitute(self, params: dict, prev_result: str) -> dict:
        """Replace {prev_result} placeholders in step params."""
        out = {}
        for k, v in params.items():
            if isinstance(v, str):
                out[k] = v.replace("{prev_result}", prev_result).replace(
                    "{{prev_result}}", prev_result
                )
            else:
                out[k] = v
        return out

    async def _emit(self, event_type: EventType, data: dict) -> None:
        event = HiveEvent(
            event_type=event_type,
            agent_id=self._agent_id,
            session_id=self._session_id,
            data=data,
        )
        await self._events.append(event)
