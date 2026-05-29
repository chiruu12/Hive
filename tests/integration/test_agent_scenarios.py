"""End-to-end agent scenarios combining multiple framework features.

These run a real Agent through the runtime with a scripted provider (no network)
to catch integration regressions across the ReAct loop, tools, streaming,
structured output, multi-toolkit merging, and error recovery.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from hive.models.base import BaseProvider
from hive.runtime.agent import Agent
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


class ScenarioProvider(BaseProvider):
    """Returns queued assistant messages; records the messages it received."""

    def __init__(self, responses: list[Message], stream_deltas: dict[int, list[str]] | None = None):
        super().__init__("scenario")
        self._responses = responses
        self._stream_deltas = stream_deltas or {}
        self._i = 0
        self.calls: list[list[Message]] = []

    @property
    def available(self) -> bool:
        return True

    def _next(self, messages: list[Message]) -> tuple[int, Message]:
        self.calls.append(list(messages))
        idx = self._i
        msg = self._responses[idx] if idx < len(self._responses) else Message.assistant("(done)")
        self._i += 1
        return idx, msg

    async def generate_with_metadata(
        self, messages: list[Message], *a: Any, **k: Any
    ) -> GenerateResult:
        _, msg = self._next(messages)
        return GenerateResult(message=msg, model="scenario", input_tokens=5, output_tokens=3)

    async def generate_stream(self, messages: list[Message], *a: Any, **k: Any):
        idx, msg = self._next(messages)
        for delta in self._stream_deltas.get(idx, []):
            yield StreamEvent(type=StreamEventType.TEXT, text=delta)
        yield StreamEvent(
            type=StreamEventType.DONE,
            result=GenerateResult(message=msg, model="scenario"),
        )


class MathKit(Toolkit):
    @tool()
    def double(self, n: int) -> str:
        """Double a number.

        Args:
            n: the number.
        """
        return str(n * 2)

    @tool()
    def add_ten(self, n: int) -> str:
        """Add ten to a number.

        Args:
            n: the number.
        """
        return str(n + 10)


class FlakyKit(Toolkit):
    """A tool that fails the first time, then succeeds."""

    def __init__(self) -> None:
        self.calls = 0

    @tool()
    def fetch(self) -> str:
        """Fetch a value (fails once)."""
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient failure")
        return "the-value"


class NoteKit(Toolkit):
    @tool()
    def remember(self, text: str) -> str:
        """Remember text.

        Args:
            text: what to remember.
        """
        return f"noted: {text}"


class TestAgentScenarios:
    @pytest.mark.asyncio
    async def test_tool_chaining_threads_results(self) -> None:
        """A multi-step run threads each tool result back into the conversation."""
        provider = ScenarioProvider(
            [
                Message.assistant("step1", [ToolCall(id="c1", name="double", arguments={"n": 5})]),
                Message.assistant(
                    "step2", [ToolCall(id="c2", name="add_ten", arguments={"n": 10})]
                ),
                Message.assistant("The answer is 20."),
            ]
        )
        agent = Agent(name="m", model=provider, toolkits=[MathKit()])
        result = await agent.run(Task(instruction="double 5 then add 10"))

        assert result.status == TaskStatus.COMPLETED
        assert result.output == "The answer is 20."
        assert result.tool_calls_made == 2
        # The double() result must be visible to the model before step 2.
        before_step2 = provider.calls[1]
        tool_msgs = [m.content for m in before_step2 if m.role == Role.TOOL]
        assert "10" in tool_msgs

    @pytest.mark.asyncio
    async def test_tool_error_then_recovery(self) -> None:
        """A tool failure surfaces as an error result; the agent can retry and finish."""
        provider = ScenarioProvider(
            [
                Message.assistant("try", [ToolCall(id="c1", name="fetch", arguments={})]),
                Message.assistant("retry", [ToolCall(id="c2", name="fetch", arguments={})]),
                Message.assistant("Got the-value."),
            ]
        )
        kit = FlakyKit()
        agent = Agent(name="r", model=provider, toolkits=[kit])
        result = await agent.run(Task(instruction="fetch with retry"))

        assert result.status == TaskStatus.COMPLETED
        assert kit.calls == 2
        first_results = [m for m in provider.calls[1] if m.role == Role.TOOL]
        assert any(m.is_error for m in first_results)  # first attempt errored

    @pytest.mark.asyncio
    async def test_multi_toolkit_no_collision(self) -> None:
        """Tools from multiple toolkits merge and are all callable."""
        provider = ScenarioProvider(
            [
                Message.assistant(
                    "both",
                    [
                        ToolCall(id="c1", name="double", arguments={"n": 3}),
                        ToolCall(id="c2", name="remember", arguments={"text": "hi"}),
                    ],
                ),
                Message.assistant("done"),
            ]
        )
        agent = Agent(name="multi", model=provider, toolkits=[MathKit(), NoteKit()])
        names = {t.name for t in agent.get_tools()}
        assert {"double", "add_ten", "remember"} <= names

        result = await agent.run(Task(instruction="use both kits"))
        assert result.tool_calls_made == 2
        tool_out = {m.content for m in provider.calls[1] if m.role == Role.TOOL}
        assert "6" in tool_out and "noted: hi" in tool_out

    @pytest.mark.asyncio
    async def test_streaming_scenario_with_tool(self) -> None:
        """Streaming an agent that also calls a tool yields deltas and the right output."""
        collected: list[str] = []
        provider = ScenarioProvider(
            responses=[
                Message.assistant("calc", [ToolCall(id="c1", name="double", arguments={"n": 7})]),
                Message.assistant("Fourteen."),
            ],
            stream_deltas={0: ["Let me ", "calc."], 1: ["Four", "teen."]},
        )
        agent = Agent(name="s", model=provider, toolkits=[MathKit()], on_text=collected.append)
        result = await agent.run(Task(instruction="double 7"))

        assert result.status == TaskStatus.COMPLETED
        assert result.output == "Fourteen."
        assert collected == ["Let me ", "calc.", "Four", "teen."]

    @pytest.mark.asyncio
    async def test_structured_then_plain_on_same_agent(self) -> None:
        """An agent supports both structured and plain one-shots."""

        class Out(BaseModel):
            answer: int

        provider = ScenarioProvider(
            [Message.assistant('{"answer": 42}'), Message.assistant("forty-two")]
        )
        agent = Agent(name="x", model=provider)

        structured = await agent.run_once_structured("give a number", output_type=Out)
        assert structured.answer == 42
        plain = await agent.run_once("spell it")
        assert plain == "forty-two"
