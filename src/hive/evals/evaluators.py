"""Built-in evaluators: accuracy (LLM judge), reliability (tools), performance (SLOs)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from hive.evals.types import CaseResult, EvalCase, EvalRun
from hive.runtime.types import Message

if TYPE_CHECKING:
    from hive.models.base import BaseProvider

_JUDGE_RUBRIC = (
    "Rate how well the actual answer satisfies the expected answer on a scale of 0 to "
    "10 (10 = fully correct and complete, 0 = wrong or missing). Reply with ONLY the "
    "number on the first line, then a one-sentence justification."
)


def _build_judge_prompt(instruction: str, expected: str, actual: str) -> str:
    """Build the judge prompt by concatenation.

    Avoids ``str.format``/f-string substitution so brace characters in the instruction,
    expected answer, or actual output (e.g. JSON like ``{"k": 1}``) can't raise.
    """
    return (
        "You are grading an AI assistant's answer.\n\n"
        f"Task given to the assistant:\n{instruction}\n\n"
        f"Expected answer (reference):\n{expected}\n\n"
        f"Assistant's actual answer:\n{actual}\n\n"
        f"{_JUDGE_RUBRIC}"
    )


class AccuracyEval:
    """LLM-as-judge: score the agent's output against an expected answer (0..1)."""

    name = "accuracy"

    def __init__(self, judge: BaseProvider, threshold: float = 0.6):
        self._judge = judge
        self._threshold = threshold

    async def evaluate(self, run: EvalRun, case: EvalCase) -> CaseResult:
        if case.expected_answer is None:
            return CaseResult(
                case, self.name, True, 1.0, "no expected_answer (skipped)", run, skipped=True
            )
        prompt = _build_judge_prompt(case.instruction, case.expected_answer, run.output)
        result = await self._judge.generate_with_metadata(messages=[Message.user(prompt)])
        score, detail = self._parse(result.message.content)
        return CaseResult(case, self.name, score >= self._threshold, score, detail, run)

    @staticmethod
    def _parse(text: str) -> tuple[float, str]:
        match = re.search(r"\b(10|\d)(?:\.\d+)?\b", text)
        if not match:
            return 0.0, f"unparseable judge reply: {text[:80]}"
        score = min(1.0, float(match.group(0)) / 10.0)
        return score, text.strip()[:200]


class ReliabilityEval:
    """Assert the agent actually called the expected tools.

    ``mode="all"`` (default): every expected tool must appear. ``mode="exact"``: the
    set of called tools must equal the expected set.
    """

    name = "reliability"

    def __init__(self, mode: str = "all"):
        if mode not in ("all", "exact"):
            raise ValueError("mode must be 'all' or 'exact'")
        self._mode = mode

    async def evaluate(self, run: EvalRun, case: EvalCase) -> CaseResult:
        expected = set(case.expected_tools or [])
        actual = set(run.tool_calls)
        if not expected:
            return CaseResult(
                case, self.name, True, 1.0, "no expected_tools (skipped)", run, skipped=True
            )
        hit = expected & actual
        score = len(hit) / len(expected)
        if self._mode == "exact":
            passed = actual == expected
        else:
            passed = expected <= actual
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        detail = f"called={sorted(actual)} missing={missing} extra={extra}"
        return CaseResult(case, self.name, passed, score, detail, run)


class PerformanceEval:
    """Check a run against latency and/or cost SLOs."""

    name = "performance"

    def __init__(self, max_seconds: float | None = None, max_cost_usd: float | None = None):
        self._max_seconds = max_seconds
        self._max_cost_usd = max_cost_usd

    async def evaluate(self, run: EvalRun, case: EvalCase) -> CaseResult:
        ok_time = self._max_seconds is None or run.duration_seconds <= self._max_seconds
        ok_cost = self._max_cost_usd is None or run.cost_usd <= self._max_cost_usd
        passed = ok_time and ok_cost
        # Score is the worse of the two budget ratios (1.0 = well within budget).
        # Guard with `is not None` (not truthiness) so a 0.0 budget is still scored --
        # otherwise passed=False could pair with an empty-ratios score of 1.0.
        ratios = []
        if self._max_seconds is not None:
            ratios.append(
                max(0.0, 1.0 - run.duration_seconds / self._max_seconds)
                if self._max_seconds > 0
                else (0.0 if run.duration_seconds > 0 else 1.0)
            )
        if self._max_cost_usd is not None:
            ratios.append(
                max(0.0, 1.0 - run.cost_usd / self._max_cost_usd)
                if self._max_cost_usd > 0
                else (0.0 if run.cost_usd > 0 else 1.0)
            )
        score = min(ratios) if ratios else 1.0
        detail = f"{run.duration_seconds:.2f}s, ${run.cost_usd:.4f}"
        return CaseResult(case, self.name, passed, score, detail, run)
