"""Run eval cases through an agent and score them with evaluators."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from hive.evals.types import EvalCase, EvalReport, EvalRun, Evaluator
from hive.runtime.types import Task

if TYPE_CHECKING:
    from hive.runtime.agent import Agent


class AgentEvalRunner:
    """Runs an ``EvalCase`` through an ``Agent``, capturing its tool-call trace.

    The same agent runs many cases, so the runner mutates shared agent state (the
    tool observer and per-run counters). A lock serializes ``run`` calls on the same
    runner: concurrent calls (e.g. ``asyncio.gather(runner.run(a), runner.run(b))``)
    would otherwise overwrite each other's observer and interleave tool traces. To
    evaluate cases in parallel, use one runner (and Agent) per concurrent run.
    """

    def __init__(self, agent: Agent):
        self._agent = agent
        self._lock = asyncio.Lock()

    async def run(self, case: EvalCase) -> EvalRun:
        async with self._lock:
            calls: list[str] = []
            # Snapshot and restore any pre-existing observer instead of clearing it,
            # so an agent built with Agent(on_tool=...) keeps its callback afterward.
            previous_on_tool = self._agent._on_tool
            self._agent.observe_tools(lambda name, args, ok: calls.append(name))
            try:
                result = await self._agent.run(
                    Task(instruction=case.instruction, context=case.context)
                )
            finally:
                self._agent.observe_tools(previous_on_tool)
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
        names = [e.name for e in evaluators]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(
                f"duplicate evaluator name(s) {dupes}: each evaluator needs a unique "
                f"name, else their reports collide"
            )
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
