"""Run eval cases through an agent and score them with evaluators."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hive.evals.types import EvalCase, EvalReport, EvalRun, Evaluator
from hive.runtime.types import Task

if TYPE_CHECKING:
    from hive.runtime.agent import Agent


class AgentEvalRunner:
    """Runs an ``EvalCase`` through an ``Agent``, capturing its tool-call trace.

    The same agent can run many cases; each run resets the agent's counters. The
    tool observer is installed for the duration of a run and removed afterward.
    """

    def __init__(self, agent: Agent):
        self._agent = agent

    async def run(self, case: EvalCase) -> EvalRun:
        calls: list[str] = []
        self._agent.observe_tools(lambda name, args, ok: calls.append(name))
        try:
            result = await self._agent.run(Task(instruction=case.instruction, context=case.context))
        finally:
            self._agent.observe_tools(None)
        return EvalRun(
            instruction=case.instruction,
            output=result.output,
            status=result.status.value,
            tool_calls=calls,
            duration_seconds=result.duration_seconds,
            cost_usd=result.cost_usd,
            steps=result.steps_taken,
        )


class EvalSuite:
    """Run a list of cases once each, scoring every run with every evaluator."""

    def __init__(self, runner: AgentEvalRunner, evaluators: list[Evaluator]):
        self._runner = runner
        self._evaluators = evaluators

    async def run(self, cases: list[EvalCase]) -> dict[str, EvalReport]:
        reports = {e.name: EvalReport(evaluator=e.name) for e in self._evaluators}
        for case in cases:
            run = await self._runner.run(case)
            for evaluator in self._evaluators:
                result = await evaluator.evaluate(run, case)
                reports[evaluator.name].results.append(result)
        return reports
