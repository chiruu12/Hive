"""Tests for contextual error messages in agent logs."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from hive.models.base import BaseProvider
from hive.runtime.agent import Agent
from hive.runtime.types import GenerateResult, Message, Task, ToolCall
from hive.tools import Toolkit, tool


class _FailProvider(BaseProvider):
    """Provider that raises on generate."""

    def __init__(self, error: Exception | None = None) -> None:
        super().__init__("fail-model")
        self._error = error

    @property
    def available(self) -> bool:
        return True

    async def generate_with_metadata(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> GenerateResult:
        if self._error:
            raise self._error
        return GenerateResult(
            message=Message.assistant("ok"),
            model="fail-model",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.0,
        )

    async def generate_structured(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


class _OkProvider(BaseProvider):
    """Provider returning configurable responses."""

    def __init__(self, responses: list[Message]) -> None:
        super().__init__("ok-model")
        self._responses = list(responses)
        self._idx = 0

    @property
    def available(self) -> bool:
        return True

    async def generate_with_metadata(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> GenerateResult:
        msg = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return GenerateResult(
            message=msg, model="ok-model", input_tokens=10, output_tokens=5, cost_usd=0.0
        )

    async def generate_structured(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


class _BrokenToolkit(Toolkit):
    @tool()
    def explode(self, msg: str = "boom") -> str:
        """A tool that always fails."""
        raise RuntimeError(f"Kaboom: {msg}")


@pytest.mark.asyncio
async def test_model_failure_logs_agent_name_and_step(caplog: pytest.LogCaptureFixture) -> None:
    agent = Agent(name="test-agent", model=_FailProvider(RuntimeError("connection reset")))
    with caplog.at_level(logging.ERROR):
        await agent.run(Task(instruction="do something"))
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("test-agent" in r.message for r in errors)
    assert any("step 1" in r.message for r in errors)
    assert any("fail-model" in r.message for r in errors)


@pytest.mark.asyncio
async def test_unknown_tool_logs_agent_name(caplog: pytest.LogCaptureFixture) -> None:
    responses = [
        Message.assistant(
            "calling tool",
            [ToolCall(id="t1", name="nonexistent_tool", arguments={})],
        ),
        Message.assistant("done"),
    ]
    agent = Agent(name="my-agent", model=_OkProvider(responses))
    with caplog.at_level(logging.WARNING):
        await agent.run(Task(instruction="test"))
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("my-agent" in r.message for r in warnings)
    assert any("nonexistent_tool" in r.message for r in warnings)


@pytest.mark.asyncio
async def test_tool_failure_logs_agent_and_args(caplog: pytest.LogCaptureFixture) -> None:
    responses = [
        Message.assistant(
            "calling tool",
            [ToolCall(id="t1", name="explode", arguments={"msg": "test-input"})],
        ),
        Message.assistant("done"),
    ]
    agent = Agent(name="err-agent", model=_OkProvider(responses), toolkits=[_BrokenToolkit()])
    with caplog.at_level(logging.WARNING):
        await agent.run(Task(instruction="test"))
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("err-agent" in r.message for r in warnings)
    assert any("explode" in r.message for r in warnings)
    assert any("test-input" in r.message for r in warnings)
