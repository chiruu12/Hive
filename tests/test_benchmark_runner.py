"""Tests for benchmark runner execution logic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hive.benchmark.runner import BenchmarkResult, BenchmarkRunner, ModelResult
from hive.models.base import GenerateResult
from hive.runtime.types import Message, Role


def _generate_result(content: str = "ok") -> GenerateResult:
    return GenerateResult(
        message=Message(role=Role.ASSISTANT, content=content),
        model="test",
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.001,
    )


class TestModelResult:
    def test_defaults(self):
        mr = ModelResult(model="test")
        assert mr.goals_completed == 0
        assert mr.goals_abandoned == 0
        assert mr.total_steps == 0
        assert mr.total_tokens == 0
        assert mr.total_cost == 0.0
        assert mr.duration_ms == 0
        assert mr.errors == 0
        assert mr.responses == []


class TestBenchmarkResult:
    def test_creation(self):
        br = BenchmarkResult(scenario="test-scenario", runs_per_model=3)
        assert br.scenario == "test-scenario"
        assert br.runs_per_model == 3
        assert br.model_results == []


class TestBenchmarkRunner:
    @pytest.mark.asyncio
    async def test_run_task_benchmark_success(self, tmp_path: Path):
        runner = BenchmarkRunner(tmp_path)

        mock_provider = MagicMock()
        mock_provider.generate_with_metadata = AsyncMock(
            return_value=_generate_result("The three laws are...")
        )

        with patch("hive.benchmark.runner.create_runtime_provider", return_value=mock_provider):
            result = await runner.run_task_benchmark(
                models=["test-model"],
                task="What are the three laws?",
                runs=2,
            )

        assert len(result.model_results) == 1
        mr = result.model_results[0]
        assert mr.model == "test-model"
        assert mr.goals_completed == 2
        assert mr.total_steps == 2
        assert mr.errors == 0
        assert len(mr.responses) == 2

    @pytest.mark.asyncio
    async def test_run_task_benchmark_provider_failure(self, tmp_path: Path):
        runner = BenchmarkRunner(tmp_path)

        with patch(
            "hive.benchmark.runner.create_runtime_provider", side_effect=Exception("No API key")
        ):
            result = await runner.run_task_benchmark(
                models=["bad-model"],
                task="test",
                runs=3,
            )

        mr = result.model_results[0]
        assert mr.errors == 3
        assert mr.goals_completed == 0

    @pytest.mark.asyncio
    async def test_run_task_benchmark_partial_failure(self, tmp_path: Path):
        runner = BenchmarkRunner(tmp_path)

        call_count = 0

        async def failing_generate(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("API timeout")
            return _generate_result("ok")

        mock_provider = MagicMock()
        mock_provider.generate_with_metadata = AsyncMock(side_effect=failing_generate)

        with patch("hive.benchmark.runner.create_runtime_provider", return_value=mock_provider):
            result = await runner.run_task_benchmark(
                models=["test-model"],
                task="test",
                runs=3,
            )

        mr = result.model_results[0]
        assert mr.goals_completed == 2
        assert mr.errors == 1

    @pytest.mark.asyncio
    async def test_run_task_benchmark_multiple_models(self, tmp_path: Path):
        runner = BenchmarkRunner(tmp_path)

        provider_a = MagicMock()
        provider_a.generate_with_metadata = AsyncMock(return_value=_generate_result("A"))

        provider_b = MagicMock()
        provider_b.generate_with_metadata = AsyncMock(return_value=_generate_result("B"))

        def factory(model_name):
            return provider_a if model_name == "model-a" else provider_b

        with patch("hive.benchmark.runner.create_runtime_provider", side_effect=factory):
            result = await runner.run_task_benchmark(
                models=["model-a", "model-b"],
                task="test",
                runs=1,
            )

        assert len(result.model_results) == 2
        assert result.model_results[0].model == "model-a"
        assert result.model_results[1].model == "model-b"

    @pytest.mark.asyncio
    async def test_run_task_benchmark_tracks_tokens_and_cost(self, tmp_path: Path):
        runner = BenchmarkRunner(tmp_path)

        mock_provider = MagicMock()
        mock_provider.generate_with_metadata = AsyncMock(return_value=_generate_result("response"))

        with patch("hive.benchmark.runner.create_runtime_provider", return_value=mock_provider):
            result = await runner.run_task_benchmark(models=["m"], task="t", runs=1)

        mr = result.model_results[0]
        assert mr.total_tokens == 15  # 10 input + 5 output
        assert mr.total_cost == pytest.approx(0.001)

    @pytest.mark.asyncio
    async def test_run_task_benchmark_records_responses(self, tmp_path: Path):
        runner = BenchmarkRunner(tmp_path)

        mock_provider = MagicMock()
        mock_provider.generate_with_metadata = AsyncMock(
            return_value=_generate_result("Hello world response")
        )

        with patch("hive.benchmark.runner.create_runtime_provider", return_value=mock_provider):
            result = await runner.run_task_benchmark(models=["m"], task="test", runs=1)

        resp = result.model_results[0].responses[0]
        assert resp["run"] == 0
        assert "Hello world response" in resp["response"]
        assert resp["tokens"] == 15

    @pytest.mark.asyncio
    async def test_run_goal_benchmark_provider_failure(self, tmp_path: Path):
        runner = BenchmarkRunner(tmp_path)

        with patch("hive.benchmark.runner.create_runtime_provider", side_effect=Exception("fail")):
            result = await runner.run_goal_benchmark(
                models=["bad-model"],
                cycles=3,
                runs=1,
            )

        assert result.model_results[0].errors == 1
