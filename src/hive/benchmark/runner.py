"""Benchmark runner — run scenarios across multiple models and compare."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hive.agents.existence import ExistenceLoop
from hive.agents.profile import AgentProfile
from hive.agents.suffering import SufferingState
from hive.memory.events import EventLog
from hive.memory.store import HiveStore
from hive.models.factory import create_runtime_provider
from hive.runtime.types import Message

logger = logging.getLogger(__name__)


@dataclass
class ModelResult:
    model: str
    goals_completed: int = 0
    goals_abandoned: int = 0
    total_steps: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    duration_ms: int = 0
    errors: int = 0
    responses: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class BenchmarkResult:
    scenario: str
    runs_per_model: int
    model_results: list[ModelResult] = field(default_factory=list)


class BenchmarkRunner:
    """Run a scenario across multiple models and collect metrics."""

    def __init__(self, hive_dir: Path):
        self._hive_dir = hive_dir
        self._store = HiveStore(hive_dir / "hive.db")
        self._events = EventLog(hive_dir)

    async def run_goal_benchmark(
        self,
        models: list[str],
        profile_name: str = "coder",
        cycles: int = 5,
        runs: int = 1,
    ) -> BenchmarkResult:
        """Run N cycles of goal generation per model and compare."""
        await self._store.initialize()

        profiles_dir = Path.cwd() / "profiles"
        try:
            profile = AgentProfile.from_preset(profile_name, profiles_dir)
        except FileNotFoundError:
            profile = AgentProfile(name="benchmark", role="Complete tasks")

        result = BenchmarkResult(
            scenario=f"goal-{cycles}-cycles",
            runs_per_model=runs,
        )

        for model_name in models:
            mr = ModelResult(model=model_name)
            try:
                provider = create_runtime_provider(model_name)
            except Exception as e:
                logger.error("Failed to create provider for %s: %s", model_name, e)
                mr.errors = runs
                result.model_results.append(mr)
                continue

            for _ in range(runs):
                start = time.monotonic()
                suffering = SufferingState()

                for cycle in range(cycles):
                    agent_id = f"bench-{model_name[:10]}-{cycle}"
                    existence = ExistenceLoop(
                        agent_id=agent_id,
                        profile=profile,
                        provider=provider,
                        store=self._store,
                        event_log=self._events,
                        economy_enabled=False,
                    )
                    try:
                        goal = await existence.generate_goal(suffering, [], [])
                        if goal:
                            mr.goals_completed += 1
                            mr.responses.append({"cycle": cycle, "goal": goal})
                        else:
                            mr.goals_abandoned += 1
                    except Exception as e:
                        mr.errors += 1
                        logger.error("Benchmark error (%s cycle %d): %s", model_name, cycle, e)
                    mr.total_steps += 1

                elapsed = int((time.monotonic() - start) * 1000)
                mr.duration_ms += elapsed

            result.model_results.append(mr)

        return result

    async def run_task_benchmark(
        self,
        models: list[str],
        task: str = "What are the three laws of robotics?",
        runs: int = 3,
    ) -> BenchmarkResult:
        """Run a single task across models and compare responses."""
        result = BenchmarkResult(scenario=f"task: {task[:40]}", runs_per_model=runs)

        for model_name in models:
            mr = ModelResult(model=model_name)
            try:
                provider = create_runtime_provider(model_name)
            except Exception as e:
                logger.error("Failed to create provider for %s: %s", model_name, e)
                mr.errors = runs
                result.model_results.append(mr)
                continue

            for i in range(runs):
                start = time.monotonic()
                try:
                    gen_result = await provider.generate_with_metadata(
                        messages=[Message.user(task)]
                    )
                    mr.total_tokens += gen_result.input_tokens + gen_result.output_tokens
                    mr.total_cost += gen_result.cost_usd or 0
                    mr.goals_completed += 1
                    mr.responses.append(
                        {
                            "run": i,
                            "response": gen_result.message.content[:500],
                            "tokens": gen_result.input_tokens + gen_result.output_tokens,
                        }
                    )
                except Exception as e:
                    mr.errors += 1
                    logger.error("Task benchmark error (%s run %d): %s", model_name, i, e)
                mr.total_steps += 1
                elapsed = int((time.monotonic() - start) * 1000)
                mr.duration_ms += elapsed

            result.model_results.append(mr)

        return result
