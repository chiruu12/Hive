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


@pytest.mark.asyncio
async def test_log_contains_tool_calls(tmp_path: Any) -> None:
    """Conversation log captures tool call details."""
    from hive.runtime.types import ToolCall
    from hive.tools import Toolkit, tool

    class _NoopToolkit(Toolkit):
        @tool()
        def greet(self, name: str = "world") -> str:
            """Say hi."""
            return f"Hello {name}"

    responses = [
        Message.assistant(
            "calling", [ToolCall(id="t1", name="greet", arguments={"name": "hive"})]
        ),
        Message.assistant("done"),
    ]
    provider = _MockProvider(responses)
    agent = Agent(
        name="tool-log",
        model=provider,
        toolkits=[_NoopToolkit()],
        conversation_log_dir=tmp_path,
    )
    await agent.run(Task(instruction="use tool"))

    files = list((tmp_path / "tool-log").glob("*.json"))
    data = json.loads(files[0].read_text())
    tool_msgs = [
        m for m in data["messages"] if m.get("tool_calls") and len(m["tool_calls"]) > 0
    ]
    assert len(tool_msgs) >= 1
    assert tool_msgs[0]["tool_calls"][0]["name"] == "greet"


@pytest.mark.asyncio
async def test_multiple_runs_create_separate_logs(tmp_path: Any) -> None:
    """Each run() creates a separate log file."""
    import time

    provider = _MockProvider([Message.assistant("ok")])
    agent = Agent(name="multi", model=provider, conversation_log_dir=tmp_path)

    await agent.run(Task(instruction="run 1"))
    time.sleep(1.1)  # ensure different second-resolution timestamp
    await agent.run(Task(instruction="run 2"))

    files = list((tmp_path / "multi").glob("*.json"))
    assert len(files) == 2


@pytest.mark.asyncio
async def test_run_once_log_includes_final_assistant_message(tmp_path: Any) -> None:
    """run_once conversation log must include the final assistant response."""
    provider = _MockProvider([Message.assistant("final answer")])
    agent = Agent(name="final-msg", model=provider, conversation_log_dir=tmp_path)
    await agent.run_once("question")

    files = list((tmp_path / "final-msg").glob("*.json"))
    data = json.loads(files[0].read_text())
    assistant_msgs = [m for m in data["messages"] if m["role"] == "assistant"]
    assert len(assistant_msgs) >= 1
    assert any("final answer" in m["content"] for m in assistant_msgs)
