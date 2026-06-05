"""Evals harness -- score agent runs for accuracy, reliability, and performance.

```python
from hive.evals import AgentEvalRunner, EvalSuite, EvalCase
from hive.evals import AccuracyEval, ReliabilityEval, PerformanceEval

suite = EvalSuite(
    AgentEvalRunner(agent),
    [AccuracyEval(judge=provider), ReliabilityEval(), PerformanceEval(max_seconds=10)],
)
reports = await suite.run([
    EvalCase("What is 2+2?", expected_answer="4", expected_tools=["calculator"]),
])
print(reports["accuracy"].summary())
```
"""

from hive.evals.evaluators import AccuracyEval, PerformanceEval, ReliabilityEval
from hive.evals.runner import AgentEvalRunner, EvalSuite
from hive.evals.types import CaseResult, EvalCase, EvalReport, EvalRun, Evaluator

__all__ = [
    "AccuracyEval",
    "PerformanceEval",
    "ReliabilityEval",
    "AgentEvalRunner",
    "EvalSuite",
    "EvalCase",
    "EvalRun",
    "CaseResult",
    "EvalReport",
    "Evaluator",
]
