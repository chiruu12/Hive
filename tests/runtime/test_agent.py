"""Tests for the Agent ReAct loop with mock providers."""

from __future__ import annotations

from typing import Any

import pytest

from hive.runtime.agent import Agent
from hive.runtime.memory import ConversationMemory
from hive.runtime.tools import Tool, Toolkit, tool
from hive.runtime.types import Message, Role, Task, TaskStatus, ToolCall


class MockProvider:
    """Provider that returns pre-programmed responses."""

    def __init__(self, responses: list[Message]):
        self._responses = list(responses)
        self._call_count = 0
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Message:
        self.calls.append(
            {
                "messages": messages,
                "tools": tools,
                "temperature": temperature,
            }
        )
        if self._call_count < len(self._responses):
            response = self._responses[self._call_count]
        else:
            response = Message.assistant("No more responses configured.")
        self._call_count += 1
        return response


class CalculatorToolkit(Toolkit):
    """Simple toolkit for testing."""

    @tool()
    def add(self, a: int, b: int) -> str:
        """Add two numbers.

        Args:
            a: First number.
            b: Second number.
        """
        return str(int(a) + int(b))

    @tool()
    def multiply(self, a: int, b: int) -> str:
        """Multiply two numbers.

        Args:
            a: First number.
            b: Second number.
        """
        return str(int(a) * int(b))


class TestReActLoop:
    @pytest.mark.asyncio
    async def test_text_only_response(self):
        """Agent returns immediately when model gives text with no tool calls."""
        provider = MockProvider([Message.assistant("The answer is 42.")])
        agent = Agent(name="test", model=provider)

        result = await agent.run(Task(instruction="What is the answer?"))
        assert result.status == TaskStatus.COMPLETED
        assert result.output == "The answer is 42."
        assert result.steps_taken == 1
        assert result.tool_calls_made == 0

    @pytest.mark.asyncio
    async def test_single_tool_call(self):
        """Agent calls a tool, gets result, then responds with text."""
        provider = MockProvider(
            [
                Message.assistant(
                    "Let me add those.",
                    [ToolCall(id="tc-1", name="add", arguments={"a": 3, "b": 4})],
                ),
                Message.assistant("The sum is 7."),
            ]
        )
        agent = Agent(
            name="calc",
            model=provider,
            toolkits=[CalculatorToolkit()],
        )

        result = await agent.run(Task(instruction="Add 3 and 4"))
        assert result.status == TaskStatus.COMPLETED
        assert result.output == "The sum is 7."
        assert result.steps_taken == 2
        assert result.tool_calls_made == 1

    @pytest.mark.asyncio
    async def test_multiple_tool_calls(self):
        """Agent calls multiple tools in sequence."""
        provider = MockProvider(
            [
                Message.assistant(
                    "Adding first.",
                    [ToolCall(id="tc-1", name="add", arguments={"a": 2, "b": 3})],
                ),
                Message.assistant(
                    "Now multiplying.",
                    [ToolCall(id="tc-2", name="multiply", arguments={"a": 5, "b": 4})],
                ),
                Message.assistant("Done: 5 + 20 = result."),
            ]
        )
        agent = Agent(
            name="calc",
            model=provider,
            toolkits=[CalculatorToolkit()],
        )

        result = await agent.run(Task(instruction="Add 2+3 then multiply 5*4"))
        assert result.status == TaskStatus.COMPLETED
        assert result.steps_taken == 3
        assert result.tool_calls_made == 2

    @pytest.mark.asyncio
    async def test_unknown_tool_error(self):
        """Agent handles calls to unknown tools gracefully."""
        provider = MockProvider(
            [
                Message.assistant(
                    "",
                    [ToolCall(id="tc-1", name="nonexistent", arguments={})],
                ),
                Message.assistant("I couldn't find that tool."),
            ]
        )
        agent = Agent(name="test", model=provider, toolkits=[CalculatorToolkit()])

        result = await agent.run(Task(instruction="Use a fake tool"))
        assert result.status == TaskStatus.COMPLETED
        assert result.tool_calls_made == 1

        second_call_messages = provider.calls[1]["messages"]
        tool_msgs = [m for m in second_call_messages if m.role == Role.TOOL]
        assert any("unknown tool" in m.content.lower() for m in tool_msgs)

    @pytest.mark.asyncio
    async def test_max_steps_exceeded(self):
        """Agent returns MAX_STEPS when it can't finish in time."""
        infinite_tools = [
            Message.assistant(
                "Calling again.",
                [ToolCall(id=f"tc-{i}", name="add", arguments={"a": 1, "b": 1})],
            )
            for i in range(20)
        ]
        provider = MockProvider(infinite_tools)
        agent = Agent(name="test", model=provider, toolkits=[CalculatorToolkit()])

        result = await agent.run(Task(instruction="Loop forever", max_steps=3))
        assert result.status == TaskStatus.MAX_STEPS
        assert result.steps_taken == 3

    @pytest.mark.asyncio
    async def test_tool_schemas_passed_to_provider(self):
        """Provider receives tool schemas when agent has tools."""
        provider = MockProvider([Message.assistant("Done.")])
        agent = Agent(
            name="test",
            model=provider,
            toolkits=[CalculatorToolkit()],
        )

        await agent.run(Task(instruction="test"))
        tools = provider.calls[0]["tools"]
        assert tools is not None
        names = {t["name"] for t in tools}
        assert "add" in names
        assert "multiply" in names

    @pytest.mark.asyncio
    async def test_system_prompt_in_messages(self):
        """System prompt is included in messages sent to provider."""
        provider = MockProvider([Message.assistant("Ok.")])
        agent = Agent(
            name="test",
            model=provider,
            system_prompt="You are a calculator.",
        )

        await agent.run(Task(instruction="hi"))
        messages = provider.calls[0]["messages"]
        system_msgs = [m for m in messages if m.role == Role.SYSTEM]
        assert any("calculator" in m.content for m in system_msgs)

    @pytest.mark.asyncio
    async def test_tool_error_handling(self):
        """Agent handles tool execution errors gracefully."""

        class FailToolkit(Toolkit):
            @tool()
            def fail(self) -> str:
                """Always fails."""
                raise RuntimeError("boom")

        provider = MockProvider(
            [
                Message.assistant(
                    "",
                    [ToolCall(id="tc-1", name="fail", arguments={})],
                ),
                Message.assistant("The tool failed."),
            ]
        )
        agent = Agent(name="test", model=provider, toolkits=[FailToolkit()])

        result = await agent.run(Task(instruction="Try failing"))
        assert result.status == TaskStatus.COMPLETED
        assert result.tool_calls_made == 1


class TestConversationMemory:
    def test_add_and_get(self):
        mem = ConversationMemory(system_prompt="sys")
        mem.add(Message.user("hello"))
        mem.add(Message.assistant("hi"))

        messages = mem.get_messages()
        assert len(messages) == 3
        assert messages[0].role == Role.SYSTEM
        assert messages[1].role == Role.USER
        assert messages[2].role == Role.ASSISTANT

    def test_truncation(self):
        mem = ConversationMemory(max_messages=3)
        for i in range(5):
            mem.add(Message.user(f"msg-{i}"))

        messages = mem.get_messages()
        assert len(messages) == 3

    def test_clear(self):
        mem = ConversationMemory()
        mem.add(Message.user("x"))
        mem.clear()
        assert mem.get_messages() == []

    def test_no_system_prompt(self):
        mem = ConversationMemory()
        mem.add(Message.user("hi"))
        messages = mem.get_messages()
        assert len(messages) == 1
        assert messages[0].role == Role.USER
