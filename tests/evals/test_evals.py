"""Tests for the evals harness."""

from __future__ import annotations

from typing import Any

import pytest

from hive.evals import (
    AccuracyEval,
    AgentEvalRunner,
    EvalCase,
    EvalSuite,
    PerformanceEval,
    ReliabilityEval,
)
from hive.evals.types import EvalRun
from hive.runtime.agent import Agent
from hive.runtime.types import GenerateResult, Message, ToolCall
from hive.tools import Toolkit, tool


class ScriptedProvider:
    """Returns a fixed sequence of assistant messages."""

    def __init__(self, responses: list[Message]):
        self._responses = list(responses)
        self._i = 0

    async def generate_with_metadata(
        self, messages: list[Message], tools: Any = None, **kw: Any
    ) -> GenerateResult:
        msg = self._responses[self._i] if self._i < len(self._responses) else Message.assistant("")
        self._i += 1
        return GenerateResult(
            message=msg, model="mock", input_tokens=3, output_tokens=2, cost_usd=0.001
        )


class CalcToolkit(Toolkit):
    @tool()
    def calculator(self, expr: str) -> str:
        """Evaluate a simple expression.

        Args:
            expr: The expression.
        """
        return "4"


def _run(output: str) -> EvalRun:
    return EvalRun(
        instruction="q",
        output=output,
        status="completed",
        tool_calls=["calculator"],
        duration_seconds=1.0,
        cost_usd=0.002,
        steps=1,
    )


class TestReliabilityEval:
    @pytest.mark.asyncio
    async def test_expected_tool_called(self) -> None:
        ev = ReliabilityEval()
        res = await ev.evaluate(_run("4"), EvalCase("q", expected_tools=["calculator"]))
        assert res.passed and res.score == 1.0

    @pytest.mark.asyncio
    async def test_missing_tool_fails(self) -> None:
        ev = ReliabilityEval()
        res = await ev.evaluate(_run("4"), EvalCase("q", expected_tools=["calculator", "search"]))
        assert not res.passed and res.score == 0.5

    @pytest.mark.asyncio
    async def test_exact_mode_rejects_extra_tools(self) -> None:
        run = EvalRun("q", "4", "completed", ["calculator", "shell"], 1.0, 0.0, 2)
        res = await ReliabilityEval(mode="exact").evaluate(
            run, EvalCase("q", expected_tools=["calculator"])
        )
        assert not res.passed


class TestPerformanceEval:
    @pytest.mark.asyncio
    async def test_within_budget_passes(self) -> None:
        res = await PerformanceEval(max_seconds=2.0, max_cost_usd=0.01).evaluate(
            _run("4"), EvalCase("q")
        )
        assert res.passed

    @pytest.mark.asyncio
    async def test_over_budget_fails(self) -> None:
        run = EvalRun("q", "4", "completed", [], 5.0, 0.0, 1)
        res = await PerformanceEval(max_seconds=2.0).evaluate(run, EvalCase("q"))
        assert not res.passed and res.score == 0.0


class TestAccuracyEval:
    @pytest.mark.asyncio
    async def test_judge_pass(self) -> None:
        judge = ScriptedProvider([Message.assistant("9\nLooks correct.")])
        res = await AccuracyEval(judge=judge).evaluate(
            _run("the answer is 4"), EvalCase("q", expected_answer="4")
        )
        assert res.passed and res.score == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_judge_fail(self) -> None:
        judge = ScriptedProvider([Message.assistant("2\nMostly wrong.")])
        res = await AccuracyEval(judge=judge, threshold=0.6).evaluate(
            _run("nonsense"), EvalCase("q", expected_answer="4")
        )
        assert not res.passed

    @pytest.mark.asyncio
    async def test_no_expected_answer_skips(self) -> None:
        judge = ScriptedProvider([])
        res = await AccuracyEval(judge=judge).evaluate(_run("x"), EvalCase("q"))
        assert res.passed and "skipped" in res.detail


class TestSuiteIntegration:
    @pytest.mark.asyncio
    async def test_suite_runs_agent_and_captures_tools(self) -> None:
        # Agent calls the calculator, then answers.
        agent = Agent(
            name="solver",
            model=ScriptedProvider(  # type: ignore[arg-type]
                [
                    Message.assistant(
                        "", [ToolCall(id="t1", name="calculator", arguments={"expr": "2+2"})]
                    ),
                    Message.assistant("The answer is 4"),
                ]
            ),
            toolkits=[CalcToolkit()],
        )
        judge = ScriptedProvider([Message.assistant("10\nCorrect.")])
        suite = EvalSuite(
            AgentEvalRunner(agent),
            [AccuracyEval(judge=judge), ReliabilityEval(), PerformanceEval(max_seconds=30)],
        )
        reports = await suite.run(
            [EvalCase("compute 2+2", expected_answer="4", expected_tools=["calculator"])]
        )
        assert reports["reliability"].pass_rate == 1.0
        assert reports["accuracy"].pass_rate == 1.0
        assert reports["performance"].pass_rate == 1.0
        # The observer was removed after the run.
        assert agent._on_tool is None
