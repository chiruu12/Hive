"""Tests for conversation history persistence."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from hive.models.base import BaseProvider
from hive.runtime.agent import Agent
from hive.runtime.types import GenerateResult, Message, Task


class _MockProvider(BaseProvider):
    def __init__(self, responses: list[Message]) -> None:
        super().__init__("mock-model")
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
            message=msg, model="mock", input_tokens=10, output_tokens=5, cost_usd=0.001
        )

    async def generate_structured(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


@pytest.mark.asyncio
async def test_conversation_log_written(tmp_path: Any) -> None:
    provider = _MockProvider([Message.assistant("hello")])
    agent = Agent(name="log-test", model=provider, conversation_log_dir=tmp_path)
    await agent.run(Task(instruction="say hi"))

    agent_dir = tmp_path / "log-test"
    assert agent_dir.exists()
    files = list(agent_dir.glob("*.json"))
    assert len(files) == 1

    data = json.loads(files[0].read_text())
    assert data["agent_id"] == "log-test"
    assert data["agent_name"] == "log-test"
    assert data["status"] == "completed"
    assert isinstance(data["messages"], list)
    assert len(data["messages"]) >= 2


@pytest.mark.asyncio
async def test_no_log_without_dir() -> None:
    provider = _MockProvider([Message.assistant("hello")])
    agent = Agent(name="no-log", model=provider)
    result = await agent.run(Task(instruction="say hi"))
    assert result.output == "hello"


@pytest.mark.asyncio
async def test_log_contains_metadata(tmp_path: Any) -> None:
    provider = _MockProvider([Message.assistant("response")])
    agent = Agent(name="meta-test", model=provider, conversation_log_dir=tmp_path)
    await agent.run(Task(instruction="go"))

    files = list((tmp_path / "meta-test").glob("*.json"))
    data = json.loads(files[0].read_text())
    assert "total_cost_usd" in data
    assert "total_tokens" in data
    assert data["total_tokens"] > 0
    assert "mock-model" in data["model"]


@pytest.mark.asyncio
async def test_log_failure_does_not_crash(tmp_path: Any) -> None:
    provider = _MockProvider([Message.assistant("ok")])
    agent = Agent(name="crash-test", model=provider, conversation_log_dir=tmp_path)

    with patch.object(type(tmp_path / "crash-test"), "mkdir", side_effect=OSError("disk full")):
        result = await agent.run(Task(instruction="test"))
    assert result.output == "ok"


@pytest.mark.asyncio
async def test_run_once_writes_log(tmp_path: Any) -> None:
    provider = _MockProvider([Message.assistant("done")])
    agent = Agent(name="once-test", model=provider, conversation_log_dir=tmp_path)
    await agent.run_once("hello")

    agent_dir = tmp_path / "once-test"
    files = list(agent_dir.glob("*.json"))
    assert len(files) == 1

    data = json.loads(files[0].read_text())
    assert data["status"] == "completed"
    assert data["task_id"] == "run_once"


@pytest.mark.asyncio
async def test_log_string_dir(tmp_path: Any) -> None:
    provider = _MockProvider([Message.assistant("ok")])
    agent = Agent(name="str-dir", model=provider, conversation_log_dir=str(tmp_path))
    await agent.run(Task(instruction="go"))

    files = list((tmp_path / "str-dir").glob("*.json"))
    assert len(files) == 1
