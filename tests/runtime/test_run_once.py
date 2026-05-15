"""Tests for Agent.run_once — lightweight request-scoped execution."""

from __future__ import annotations

from typing import Any

import pytest

from hive.runtime.agent import Agent
from hive.runtime.tools import collect_tools, make_tool, tool
from hive.runtime.types import GenerateResult, Message, ToolCall


class MockOnceProvider:
    """Provider that returns pre-programmed responses."""

    def __init__(self, responses: list[Message]):
        self._responses = list(responses)
        self._idx = 0
        self.calls: list[list[Message]] = []

    @property
    def available(self) -> bool:
        return True

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Message:
        result = await self.generate_with_metadata(
            messages, tools, temperature, max_tokens,
        )
        return result.message

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
            message=msg, model="mock", input_tokens=10,
            output_tokens=5, cost_usd=0.0, duration_ms=10,
        )


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

        provider = MockOnceProvider([
            Message.assistant(
                "Let me add those.",
                [ToolCall(id="tc-1", name="add", arguments={"a": 3, "b": 4})],
            ),
            Message.assistant("The answer is 7."),
        ])
        agent = Agent("test", provider, tools=[make_tool(add)])
        result = await agent.run_once("What is 3+4?")
        assert "7" in result

    @pytest.mark.asyncio
    async def test_unknown_tool(self) -> None:
        provider = MockOnceProvider([
            Message.assistant(
                "Calling unknown.",
                [ToolCall(id="tc-1", name="nonexistent", arguments={})],
            ),
            Message.assistant("I couldn't find that tool."),
        ])
        agent = Agent("test", provider)
        result = await agent.run_once("Do something")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_tool_error_handled(self) -> None:
        @tool()
        def fail_tool() -> str:
            """Always fails."""
            raise ValueError("boom")

        provider = MockOnceProvider([
            Message.assistant(
                "Trying.",
                [ToolCall(id="tc-1", name="fail_tool", arguments={})],
            ),
            Message.assistant("That failed."),
        ])
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

        provider = MockOnceProvider([
            Message.assistant(
                "Greeting.",
                [ToolCall(
                    id="tc-1", name="greet",
                    arguments={"name": "Alice"},
                )],
            ),
            Message.assistant("I greeted Alice."),
        ])
        agent = Agent(
            "test", provider, tools=collect_tools(greet, farewell),
        )
        result = await agent.run_once("Greet Alice")
        assert "Alice" in result


class TestRunOnceSync:
    def test_sync_wrapper(self) -> None:
        provider = MockOnceProvider([Message.assistant("Sync works!")])
        agent = Agent("test", provider)
        result = agent.run_once_sync("Test")
        assert result == "Sync works!"
