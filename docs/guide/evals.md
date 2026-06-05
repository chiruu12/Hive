# Evals

The evals harness scores agent runs so you can measure quality and catch
regressions. Each case runs through the agent once and is judged on three axes:

- **Accuracy** -- LLM-as-judge scores the output against an expected answer (0..1).
- **Reliability** -- asserts the agent actually called the expected tools.
- **Performance** -- checks latency and cost against SLOs.

## Quick start

```python
from hive.evals import (
    AgentEvalRunner, EvalSuite, EvalCase,
    AccuracyEval, ReliabilityEval, PerformanceEval,
)
from hive.runtime import Agent
from hive.models.anthropic import Anthropic

agent = Agent(name="solver", model=Anthropic.lite(), toolkits=[...])

suite = EvalSuite(
    AgentEvalRunner(agent),
    [
        AccuracyEval(judge=Anthropic.standard(), threshold=0.6),
        ReliabilityEval(),                     # expected tools must be called
        PerformanceEval(max_seconds=10, max_cost_usd=0.02),
    ],
)

reports = await suite.run([
    EvalCase(
        "What is 17 * 23?",
        expected_answer="391",
        expected_tools=["calculator"],
    ),
])

for name, report in reports.items():
    print(report.summary())
    # {'evaluator': 'accuracy', 'total': 1, 'passed': 1, 'pass_rate': 1.0, 'mean_score': 0.9}
```

## Cases

An `EvalCase` carries the instruction plus what a good run should produce. Fields are
optional -- an evaluator with nothing to check (e.g. accuracy with no
`expected_answer`) passes the case as skipped.

| Field | Used by | Meaning |
|-------|---------|---------|
| `instruction` | all | The task given to the agent |
| `expected_answer` | accuracy | Reference answer the judge grades against |
| `expected_tools` | reliability | Tool names the agent should call |
| `context` | all | Extra context passed into the task |

## Evaluators

| Evaluator | Pass condition | Score |
|-----------|----------------|-------|
| `AccuracyEval(judge, threshold=0.6)` | judge score ≥ threshold | judge's 0..10 rating / 10 |
| `ReliabilityEval(mode="all")` | expected tools called (`"exact"` = exact set) | fraction of expected tools hit |
| `PerformanceEval(max_seconds, max_cost_usd)` | within both budgets | headroom against the tighter budget |

## Reports

`suite.run(cases)` returns `{evaluator_name: EvalReport}`. An `EvalReport` exposes
`total`, `passed`, `pass_rate`, `mean_score`, and `summary()`, plus the per-case
`results` (each with `passed`, `score`, `detail`, and the captured `run`).

## Custom evaluators

Implement the `Evaluator` protocol (a `name` and an async `evaluate(run, case)`
returning a `CaseResult`) and drop it into the suite alongside the built-ins.

```python
from hive.evals.types import CaseResult, EvalCase, EvalRun

class NonEmptyEval:
    name = "non_empty"

    async def evaluate(self, run: EvalRun, case: EvalCase) -> CaseResult:
        ok = bool(run.output.strip())
        return CaseResult(case, self.name, ok, 1.0 if ok else 0.0, "", run)
```
