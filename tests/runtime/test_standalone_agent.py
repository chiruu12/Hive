"""The runtime Agent runs standalone -- no daemon, no .hive, no global state (E2).

These tests use only the public ``hive`` API and a small scripted provider, so
they double as the executable spec for the "2-line Agent" story in the docs.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from hive import Agent, Task, Toolkit, tool
from hive.models.base import BaseProvider
from hive.runtime.types import GenerateResult, Message, ToolCall


class ScriptedProvider(BaseProvider):
    """Returns a fixed sequence of assistant messages -- no network, no key."""

    def __init__(self, responses: list[Message]):
        super().__init__("scripted")
        self._responses = list(responses)
        self._i = 0

    @property
    def available(self) -> bool:
        return True

    async def generate_with_metadata(self, *args: Any, **kwargs: Any) -> GenerateResult:
        msg = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return GenerateResult(message=msg, model="scripted", input_tokens=5, output_tokens=3)

    # No generate_structured override: relies on the BaseProvider fallback (A4).


class Calc(Toolkit):
    @tool()
    def add(self, a: int, b: int) -> str:
        """Add two numbers.

        Args:
            a: First number.
            b: Second number.
        """
        return str(a + b)


class TestStandaloneAgent:
    @pytest.mark.asyncio
    async def test_two_line_usage(self):
        """The headline: construct and run with no daemon involved."""
        agent = Agent(name="helper", model=ScriptedProvider([Message.assistant("42")]))
        result = await agent.run(Task(instruction="What is the answer?"))
        assert result.status.value == "completed"
        assert result.output == "42"

    @pytest.mark.asyncio
    async def test_runs_tools_standalone(self):
        provider = ScriptedProvider(
            [
                Message.assistant(
                    "Adding.", [ToolCall(id="t1", name="add", arguments={"a": 2, "b": 3})]
                ),
                Message.assistant("The answer is 5."),
            ]
        )
        agent = Agent(name="calc", model=provider, toolkits=[Calc()])
        result = await agent.run(Task(instruction="add 2 and 3"))
        assert result.output == "The answer is 5."
        assert result.tool_calls_made == 1

    def test_run_once_sync(self):
        """Fully synchronous one-shot -- usable from a plain script."""
        agent = Agent(name="q", model=ScriptedProvider([Message.assistant("Paris")]))
        assert agent.run_once_sync("Capital of France?") == "Paris"

    @pytest.mark.asyncio
    async def test_run_once_async(self):
        agent = Agent(name="q", model=ScriptedProvider([Message.assistant("blue")]))
        assert await agent.run_once("Sky color?") == "blue"

    @pytest.mark.asyncio
    async def test_structured_output_via_base_fallback(self):
        class Person(BaseModel):
            name: str
            age: int

        provider = ScriptedProvider([Message.assistant('{"name": "Ada", "age": 36}')])
        agent = Agent(name="x", model=provider)
        result = await agent.run_structured(Task(instruction="Make a person"), output_type=Person)
        assert result.parsed.name == "Ada"
        assert result.parsed.age == 36

    @pytest.mark.asyncio
    async def test_agent_construction_uses_only_runtime(self):
        """The Agent class lives in the runtime, separate from the daemon package."""
        assert Agent.__module__.startswith("hive.runtime")
        agent = Agent(name="z", model=ScriptedProvider([Message.assistant("ok")]))
        result = await agent.run(Task(instruction="hi"))
        assert result.output == "ok"
