"""Tests for Agent.run_once — lightweight request-scoped execution."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel

from hive.models.base import BaseProvider
from hive.runtime.agent import Agent
from hive.runtime.structured import StructuredGenerateResult
from hive.runtime.tools import collect_tools, make_tool, tool
from hive.runtime.types import GenerateResult, Message, ToolCall


class MockOnceProvider(BaseProvider):
    """Provider that returns pre-programmed responses."""

    def __init__(self, responses: list[Message]):
        super().__init__("mock")
        self._responses = list(responses)
        self._idx = 0
        self.calls: list[list[Message]] = []

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
        self.calls.append(list(messages))
        msg = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return GenerateResult(
            message=msg,
            model="mock",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.0,
            duration_ms=10,
        )

    async def generate_structured(
        self,
        messages: list[Message],
        output_type: type[Any],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Any:
        raise NotImplementedError("MockOnceProvider does not support structured output")


class TestRunOnceTextOnly:
    @pytest.mark.asyncio
    async def test_returns_text(self) -> None:
        provider = MockOnceProvider([Message.assistant("Hello there!")])
        agent = Agent("test", provider)
        result = await agent.run_once("Hi")
        assert result == "Hello there!"

    @pytest.mark.asyncio
    async def test_with_system_prompt(self) -> None:
        provider = MockOnceProvider([Message.assistant("I'm helpful")])
        agent = Agent("test", provider, system_prompt="Be helpful.")
        result = await agent.run_once("Help me")
        assert result == "I'm helpful"
        assert provider.calls[0][0].content == "Be helpful."

    @pytest.mark.asyncio
    async def test_with_context(self) -> None:
        provider = MockOnceProvider([Message.assistant("Got it")])
        agent = Agent("test", provider, system_prompt="Base prompt.")
        await agent.run_once("Do stuff", context="Extra info here.")
        assert len(provider.calls[0]) == 3
        assert provider.calls[0][1].content == "Extra info here."


class TestRunOnceWithTools:
    @pytest.mark.asyncio
    async def test_executes_tools(self) -> None:
        @tool()
        def add(a: int, b: int) -> str:
            """Add two numbers."""
            return str(a + b)

        provider = MockOnceProvider(
            [
                Message.assistant(
                    "Let me add those.",
                    [ToolCall(id="tc-1", name="add", arguments={"a": 3, "b": 4})],
                ),
                Message.assistant("The answer is 7."),
            ]
        )
        agent = Agent("test", provider, tools=[make_tool(add)])
        result = await agent.run_once("What is 3+4?")
        assert "7" in result

    @pytest.mark.asyncio
    async def test_unknown_tool(self) -> None:
        provider = MockOnceProvider(
            [
                Message.assistant(
                    "Calling unknown.",
                    [ToolCall(id="tc-1", name="nonexistent", arguments={})],
                ),
                Message.assistant("I couldn't find that tool."),
            ]
        )
        agent = Agent("test", provider)
        result = await agent.run_once("Do something")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_tool_error_handled(self) -> None:
        @tool()
        def fail_tool() -> str:
            """Always fails."""
            raise ValueError("boom")

        provider = MockOnceProvider(
            [
                Message.assistant(
                    "Trying.",
                    [ToolCall(id="tc-1", name="fail_tool", arguments={})],
                ),
                Message.assistant("That failed."),
            ]
        )
        agent = Agent("test", provider, tools=[make_tool(fail_tool)])
        result = await agent.run_once("Try the tool")
        assert isinstance(result, str)


class TestRunOnceWithCollectTools:
    @pytest.mark.asyncio
    async def test_standalone_functions(self) -> None:
        def greet(name: str) -> str:
            """Greet someone."""
            return f"Hello, {name}!"

        def farewell(name: str) -> str:
            """Say goodbye."""
            return f"Bye, {name}!"

        provider = MockOnceProvider(
            [
                Message.assistant(
                    "Greeting.",
                    [
                        ToolCall(
                            id="tc-1",
                            name="greet",
                            arguments={"name": "Alice"},
                        )
                    ],
                ),
                Message.assistant("I greeted Alice."),
            ]
        )
        agent = Agent(
            "test",
            provider,
            tools=collect_tools(greet, farewell),
        )
        result = await agent.run_once("Greet Alice")
        assert "Alice" in result


class TestRunOnceSync:
    def test_sync_wrapper(self) -> None:
        provider = MockOnceProvider([Message.assistant("Sync works!")])
        agent = Agent("test", provider)
        result = agent.run_once_sync("Test")
        assert result == "Sync works!"


class MockStructuredProvider(MockOnceProvider):
    """Provider that supports generate_structured via tool forcing."""

    def __init__(self, structured_data: dict[str, Any]):
        super().__init__([])
        self._structured_data = structured_data

    async def generate_structured(  # type: ignore[override]
        self,
        messages: list[Message],
        output_type: type[Any],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> StructuredGenerateResult[Any]:
        parsed = output_type.model_validate(self._structured_data)
        gen = GenerateResult(
            message=Message.assistant(json.dumps(self._structured_data)),
            model="mock",
            input_tokens=10,
            output_tokens=10,
            cost_usd=0.0,
            duration_ms=10,
        )
        return StructuredGenerateResult(result=gen, parsed=parsed)


class TaskItem(BaseModel):
    title: str
    priority: int = 3
    done: bool = False


class SentimentResult(BaseModel):
    sentiment: str
    confidence: float


class TestRunOnceStructured:
    @pytest.mark.asyncio
    async def test_returns_pydantic_model(self) -> None:
        provider = MockStructuredProvider(
            {"title": "Buy groceries", "priority": 1, "done": False},
        )
        agent = Agent("test", provider)
        result = await agent.run_once_structured(
            "Create a task",
            output_type=TaskItem,
        )
        assert isinstance(result, TaskItem)
        assert result.title == "Buy groceries"
        assert result.priority == 1

    @pytest.mark.asyncio
    async def test_with_context(self) -> None:
        provider = MockStructuredProvider(
            {"sentiment": "positive", "confidence": 0.95},
        )
        agent = Agent("test", provider)
        result = await agent.run_once_structured(
            "Analyze this",
            output_type=SentimentResult,
            context="The user is happy.",
        )
        assert isinstance(result, SentimentResult)
        assert result.sentiment == "positive"
        assert result.confidence == 0.95

    @pytest.mark.asyncio
    async def test_with_system_prompt(self) -> None:
        provider = MockStructuredProvider(
            {"title": "Test", "priority": 5, "done": True},
        )
        agent = Agent("test", provider, system_prompt="Be structured.")
        result = await agent.run_once_structured(
            "Make a task",
            output_type=TaskItem,
        )
        assert result.done is True

    def test_sync_wrapper(self) -> None:
        provider = MockStructuredProvider(
            {"title": "Sync task", "priority": 2, "done": False},
        )
        agent = Agent("test", provider)
        result = agent.run_once_structured_sync(
            "Create task",
            output_type=TaskItem,
        )
        assert isinstance(result, TaskItem)
        assert result.title == "Sync task"


class TestMaxTokensConfig:
    @pytest.mark.asyncio
    async def test_custom_max_tokens_passed(self) -> None:
        provider = MockOnceProvider([Message.assistant("OK")])
        agent = Agent("test", provider, max_tokens=2048)
        await agent.run_once("Test")
        call_msgs = provider.calls[0]
        assert len(call_msgs) > 0

    @pytest.mark.asyncio
    async def test_default_max_tokens(self) -> None:
        agent = Agent("test", MockOnceProvider([]), max_tokens=0)
        assert agent._gen_max_tokens == 4096

    @pytest.mark.asyncio
    async def test_explicit_max_tokens(self) -> None:
        agent = Agent("test", MockOnceProvider([]), max_tokens=1024)
        assert agent._gen_max_tokens == 1024
