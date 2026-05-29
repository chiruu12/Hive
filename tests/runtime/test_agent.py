"""Tests for the Agent ReAct loop with mock providers."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from hive.models.base import BaseProvider, Capability
from hive.runtime.agent import Agent
from hive.runtime.memory import ConversationMemory
from hive.runtime.types import (
    GenerateResult,
    Message,
    Role,
    StreamEvent,
    StreamEventType,
    Task,
    TaskStatus,
    ToolCall,
)
from hive.tools import Toolkit, tool


class MockProvider(BaseProvider):
    """Provider that returns pre-programmed responses."""

    def __init__(self, responses: list[Message]):
        super().__init__("mock-model")
        self._responses = list(responses)
        self._call_count = 0
        self.calls: list[dict[str, Any]] = []

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
        return GenerateResult(
            message=response,
            model="mock-model",
            input_tokens=10,
            output_tokens=5,
        )

    async def generate_structured(
        self,
        messages: list[Message],
        output_type: type[Any],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Any:
        raise NotImplementedError("MockProvider does not support structured output")


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


class ConcurrencyToolkit(Toolkit):
    """Tool whose calls record peak concurrency and completion order."""

    def __init__(self) -> None:
        self.active = 0
        self.peak = 0
        self.completed: list[str] = []

    @tool()
    async def slow(self, label: str, delay: float) -> str:
        """Sleep for ``delay`` seconds then return the label.

        Args:
            label: Identifier echoed back in the result.
            delay: Seconds to sleep before returning.
        """
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(delay)
        finally:
            self.active -= 1
        self.completed.append(label)
        return f"done:{label}"


class MixedToolkit(Toolkit):
    """One succeeding and one raising tool, for error-isolation tests."""

    @tool()
    def ok(self) -> str:
        """Always succeeds."""
        return "ok-result"

    @tool()
    def boom(self) -> str:
        """Always raises."""
        raise RuntimeError("kaboom")


class TestParallelToolExecution:
    """A1: multiple tool calls in one turn run concurrently, results stay ordered."""

    @pytest.mark.asyncio
    async def test_tools_run_concurrently(self):
        """Two tool calls in one turn overlap (peak concurrency 2), not sequential."""
        toolkit = ConcurrencyToolkit()
        provider = MockProvider(
            [
                Message.assistant(
                    "Running both.",
                    [
                        ToolCall(
                            id="tc-1", name="slow", arguments={"label": "first", "delay": 0.15}
                        ),
                        ToolCall(
                            id="tc-2", name="slow", arguments={"label": "second", "delay": 0.05}
                        ),
                    ],
                ),
                Message.assistant("Both done."),
            ]
        )
        agent = Agent(name="calc", model=provider, toolkits=[toolkit])

        result = await agent.run(Task(instruction="Run both tools"))

        assert result.status == TaskStatus.COMPLETED
        assert result.tool_calls_made == 2
        # Both tools were in-flight at the same time -- deterministic proof of
        # concurrency without relying on a load-sensitive wall-clock threshold.
        assert toolkit.peak == 2
        # Shorter-delay tool finished first -> truly concurrent, not sequential.
        assert toolkit.completed == ["second", "first"]

    @pytest.mark.asyncio
    async def test_results_appended_in_call_order(self):
        """Results are appended in the original tool_calls order, not completion order."""
        toolkit = ConcurrencyToolkit()
        provider = MockProvider(
            [
                Message.assistant(
                    "Running both.",
                    [
                        ToolCall(
                            id="tc-1", name="slow", arguments={"label": "first", "delay": 0.15}
                        ),
                        ToolCall(
                            id="tc-2", name="slow", arguments={"label": "second", "delay": 0.05}
                        ),
                    ],
                ),
                Message.assistant("Both done."),
            ]
        )
        agent = Agent(name="calc", model=provider, toolkits=[toolkit])

        await agent.run(Task(instruction="Run both tools"))

        tool_msgs = [m for m in provider.calls[1]["messages"] if m.role == Role.TOOL]
        assert [m.tool_call_id for m in tool_msgs] == ["tc-1", "tc-2"]
        assert tool_msgs[0].content == "done:first"
        assert tool_msgs[1].content == "done:second"

    @pytest.mark.asyncio
    async def test_error_isolation_across_calls(self):
        """A raising tool and an unknown tool don't affect a sibling that succeeds."""
        provider = MockProvider(
            [
                Message.assistant(
                    "",
                    [
                        ToolCall(id="tc-1", name="ok", arguments={}),
                        ToolCall(id="tc-2", name="boom", arguments={}),
                        ToolCall(id="tc-3", name="missing", arguments={}),
                    ],
                ),
                Message.assistant("Handled."),
            ]
        )
        agent = Agent(name="test", model=provider, toolkits=[MixedToolkit()])

        result = await agent.run(Task(instruction="Mixed outcomes"))
        assert result.status == TaskStatus.COMPLETED
        assert result.tool_calls_made == 3

        tool_msgs = {
            m.tool_call_id: m for m in provider.calls[1]["messages"] if m.role == Role.TOOL
        }
        assert [m.tool_call_id for m in provider.calls[1]["messages"] if m.role == Role.TOOL] == [
            "tc-1",
            "tc-2",
            "tc-3",
        ]
        assert tool_msgs["tc-1"].is_error is False
        assert tool_msgs["tc-1"].content == "ok-result"
        assert tool_msgs["tc-2"].is_error is True
        assert "kaboom" in tool_msgs["tc-2"].content
        assert tool_msgs["tc-3"].is_error is True
        assert "unknown tool" in tool_msgs["tc-3"].content.lower()


class StreamingProvider(BaseProvider):
    """Provider that streams pre-programmed text deltas per turn (A2)."""

    CAPABILITIES = BaseProvider.CAPABILITIES | {Capability.STREAMING}

    def __init__(self, turns: list[tuple[list[str], GenerateResult]]):
        super().__init__("stream-model")
        self._turns = list(turns)
        self._i = 0

    @property
    def available(self) -> bool:
        return True

    async def generate_with_metadata(self, *args: Any, **kwargs: Any) -> GenerateResult:
        _, result = self._turns[min(self._i, len(self._turns) - 1)]
        return result

    async def generate_structured(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    async def generate_stream(self, *args: Any, **kwargs: Any):
        deltas, result = self._turns[self._i]
        self._i += 1
        for delta in deltas:
            yield StreamEvent(type=StreamEventType.TEXT, text=delta)
        yield StreamEvent(type=StreamEventType.DONE, result=result)


class NoDoneProvider(BaseProvider):
    """Streams text but never emits the terminal DONE event (a broken provider)."""

    @property
    def available(self) -> bool:
        return True

    async def generate_with_metadata(self, *args: Any, **kwargs: Any) -> GenerateResult:
        return GenerateResult(message=Message.assistant("x"), model="nodone")

    async def generate_stream(self, *args: Any, **kwargs: Any):
        yield StreamEvent(type=StreamEventType.TEXT, text="partial")
        # intentionally no DONE event


class TestStreaming:
    """A2: the agent's optional on_text path forwards streamed text deltas."""

    @pytest.mark.asyncio
    async def test_stream_without_done_event_fails_cleanly(self):
        """A stream missing the terminal DONE event surfaces a clear failure."""
        agent = Agent(name="x", model=NoDoneProvider("nodone"), on_text=lambda t: None)
        result = await agent.run(Task(instruction="hi"))
        assert result.status == TaskStatus.FAILED
        assert "DONE" in (result.error or "")

    @pytest.mark.asyncio
    async def test_on_text_via_base_default(self):
        """A non-streaming provider still drives on_text via the base default."""
        collected: list[str] = []
        provider = MockProvider([Message.assistant("Hello there.")])
        agent = Agent(name="test", model=provider, on_text=collected.append)

        result = await agent.run(Task(instruction="hi"))
        assert result.status == TaskStatus.COMPLETED
        assert result.output == "Hello there."
        assert collected == ["Hello there."]

    @pytest.mark.asyncio
    async def test_on_text_receives_deltas(self):
        """A streaming provider's deltas are forwarded in order."""
        collected: list[str] = []
        done = GenerateResult(message=Message.assistant("Hello"), model="stream-model")
        provider = StreamingProvider([(["Hel", "lo"], done)])
        agent = Agent(name="test", model=provider, on_text=collected.append)

        result = await agent.run(Task(instruction="hi"))
        assert result.status == TaskStatus.COMPLETED
        assert result.output == "Hello"
        assert collected == ["Hel", "lo"]

    @pytest.mark.asyncio
    async def test_streaming_with_tool_calls(self):
        """The DONE result drives tool execution; deltas across turns are forwarded."""
        collected: list[str] = []
        turn1 = GenerateResult(
            message=Message.assistant(
                "Let me add.",
                [ToolCall(id="tc-1", name="add", arguments={"a": 2, "b": 3})],
            ),
            model="stream-model",
        )
        turn2 = GenerateResult(message=Message.assistant("The sum is 5."), model="stream-model")
        provider = StreamingProvider([(["Let me ", "add."], turn1), (["The sum ", "is 5."], turn2)])
        agent = Agent(
            name="calc", model=provider, toolkits=[CalculatorToolkit()], on_text=collected.append
        )

        result = await agent.run(Task(instruction="add 2 and 3"))
        assert result.status == TaskStatus.COMPLETED
        assert result.output == "The sum is 5."
        assert result.tool_calls_made == 1
        assert collected == ["Let me ", "add.", "The sum ", "is 5."]


class TestProviderMetadata:
    @pytest.mark.asyncio
    async def test_generate_with_metadata(self):
        """generate_with_metadata returns GenerateResult with metadata."""
        provider = MockProvider([Message.assistant("hello")])
        result = await provider.generate_with_metadata(
            messages=[Message.user("hi")],
        )
        assert result.message.content == "hello"
        assert result.model == "mock-model"
        assert result.input_tokens == 10
        assert result.output_tokens == 5

    @pytest.mark.asyncio
    async def test_generate_delegates_to_metadata(self):
        """generate() returns only the message from generate_with_metadata()."""
        provider = MockProvider([Message.assistant("world")])
        msg = await provider.generate(messages=[Message.user("hi")])
        assert msg.content == "world"
        assert msg.role == Role.ASSISTANT

    @pytest.mark.asyncio
    async def test_available_property(self):
        """MockProvider reports availability."""
        provider = MockProvider([])
        assert provider.available is True


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
