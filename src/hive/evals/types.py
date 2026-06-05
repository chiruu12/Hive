"""Core types for the evals harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class EvalCase:
    """One test case: an instruction plus what a good run should produce."""

    instruction: str
    name: str = ""
    expected_answer: str | None = None  # for AccuracyEval (LLM-judged)
    expected_tools: list[str] | None = None  # for ReliabilityEval
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalRun:
    """Captured outcome of running one case through an agent."""

    instruction: str
    output: str
    status: str
    tool_calls: list[str]
    duration_seconds: float
    cost_usd: float
    steps: int


@dataclass
class CaseResult:
    """An evaluator's verdict for one case."""

    case: EvalCase
    evaluator: str
    passed: bool
    score: float  # 0.0 .. 1.0
    detail: str
    run: EvalRun
    # True when the evaluator had nothing to check for this case; excluded from the
    # report's pass-rate and mean-score so skipped cases don't inflate the metrics.
    skipped: bool = False


@dataclass
class EvalReport:
    """Aggregate results for one evaluator across all cases.

    Rates and means are computed over *scored* (non-skipped) results only.
    """

    evaluator: str
    results: list[CaseResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def _scored(self) -> list[CaseResult]:
        return [r for r in self.results if not r.skipped]

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.skipped)

    @property
    def passed(self) -> int:
        return sum(1 for r in self._scored if r.passed)

    @property
    def pass_rate(self) -> float:
        scored = len(self._scored)
        return self.passed / scored if scored else 0.0

    @property
    def mean_score(self) -> float:
        scored = self._scored
        return sum(r.score for r in scored) / len(scored) if scored else 0.0

    def summary(self) -> dict[str, Any]:
        return {
            "evaluator": self.evaluator,
            "total": self.total,
            "scored": len(self._scored),
            "skipped": self.skipped,
            "passed": self.passed,
            "pass_rate": round(self.pass_rate, 3),
            "mean_score": round(self.mean_score, 3),
        }


@runtime_checkable
class Evaluator(Protocol):
    """Scores a single captured run against its case."""

    name: str

    async def evaluate(self, run: EvalRun, case: EvalCase) -> CaseResult:
        """Return a CaseResult judging this run for ``case``."""
        ...
