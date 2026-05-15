"""Tests for robustness features — retry, budget, delegation, goal validation."""

from __future__ import annotations

from typing import Any

import pytest

from hive.runtime.agent import Agent
from hive.runtime.delegation import DelegationToolkit
from hive.runtime.tools import Toolkit, tool
from hive.runtime.types import GenerateResult, Message, Task, TaskStatus, ToolCall


class MockProvider:
    """Provider with configurable responses."""

    def __init__(self, responses: list[Message], cost_per_call: float = 0.001) -> None:
        self._responses = list(responses)
        self._call_count = 0
        self._cost = cost_per_call

    @property
    def available(self) -> bool:
        return True

    async def generate(self, messages: list[Message], **kwargs: Any) -> Message:
        result = await self.generate_with_metadata(messages, **kwargs)
        return result.message

    async def generate_with_metadata(
        self, messages: list[Message], **kwargs: Any
    ) -> GenerateResult:
        if self._call_count < len(self._responses):
            response = self._responses[self._call_count]
        else:
            response = Message.assistant("Done.")
        self._call_count += 1
        return GenerateResult(
            message=response,
            model="mock",
            input_tokens=100,
            output_tokens=50,
            cost_usd=self._cost,
        )


class TestBudgetEnforcement:
    @pytest.mark.asyncio
    async def test_cost_budget_stops_agent(self) -> None:
        responses = [
            Message.assistant("step 1", [ToolCall(id="t1", name="noop", arguments={})]),
            Message.assistant("step 2", [ToolCall(id="t2", name="noop", arguments={})]),
            Message.assistant("step 3", [ToolCall(id="t3", name="noop", arguments={})]),
            Message.assistant("done"),
        ]

        class NoopToolkit(Toolkit):
            @tool()
            def noop(self) -> str:
                """Do nothing."""
                return "ok"

        provider = MockProvider(responses, cost_per_call=0.05)
        agent = Agent(
            name="test",
            model=provider,
            toolkits=[NoopToolkit()],
            max_cost_usd=0.10,
        )

        result = await agent.run(Task(instruction="do stuff"))
        assert result.status == TaskStatus.FAILED
        assert result.error is not None
        assert "budget" in result.error.lower() or "cost" in result.error.lower()
        assert result.steps_taken < 4

    @pytest.mark.asyncio
    async def test_token_budget_stops_agent(self) -> None:
        responses = [
            Message.assistant("step 1", [ToolCall(id="t1", name="noop", arguments={})]),
            Message.assistant("step 2", [ToolCall(id="t2", name="noop", arguments={})]),
            Message.assistant("done"),
        ]

        class NoopToolkit(Toolkit):
            @tool()
            def noop(self) -> str:
                """Do nothing."""
                return "ok"

        provider = MockProvider(responses)
        agent = Agent(
            name="test",
            model=provider,
            toolkits=[NoopToolkit()],
            max_tokens=200,
        )

        result = await agent.run(Task(instruction="do stuff"))
        assert result.status == TaskStatus.FAILED
        assert "token" in (result.error or "").lower() or "budget" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_no_budget_runs_normally(self) -> None:
        provider = MockProvider([Message.assistant("done")])
        agent = Agent(name="test", model=provider)

        result = await agent.run(Task(instruction="hi"))
        assert result.status == TaskStatus.COMPLETED


class TestDelegationToolkit:
    @pytest.mark.asyncio
    async def test_delegate_success(self) -> None:
        worker = Agent(
            name="worker",
            model=MockProvider([Message.assistant("Task completed: result is 42")]),
        )
        toolkit = DelegationToolkit({"worker": worker})
        tools = toolkit.get_tools()

        delegate = next(t for t in tools if t.name == "delegate_task")
        result = await delegate.call(agent_name="worker", task="compute 6*7")
        assert "completed" in result.lower()
        assert "42" in result

    @pytest.mark.asyncio
    async def test_delegate_unknown_agent(self) -> None:
        toolkit = DelegationToolkit({"worker": Agent(name="w", model=MockProvider([]))})
        tools = toolkit.get_tools()

        delegate = next(t for t in tools if t.name == "delegate_task")
        result = await delegate.call(agent_name="nonexistent", task="do something")
        assert "not found" in result.lower()
        assert "worker" in result

    @pytest.mark.asyncio
    async def test_list_agents(self) -> None:
        toolkit = DelegationToolkit(
            {
                "coder": Agent(name="coder", model=MockProvider([])),
                "reviewer": Agent(name="reviewer", model=MockProvider([])),
            }
        )
        tools = toolkit.get_tools()

        list_tool = next(t for t in tools if t.name == "list_agents")
        result = await list_tool.call()
        assert "coder" in result
        assert "reviewer" in result

    @pytest.mark.asyncio
    async def test_delegation_in_agent_loop(self) -> None:
        """Leader agent delegates to worker via tool call."""
        worker = Agent(
            name="worker",
            model=MockProvider([Message.assistant("Worker result: done")]),
        )
        delegation = DelegationToolkit({"worker": worker})

        leader = Agent(
            name="leader",
            model=MockProvider(
                [
                    Message.assistant(
                        "I'll delegate this.",
                        [
                            ToolCall(
                                id="d1",
                                name="delegate_task",
                                arguments={"agent_name": "worker", "task": "do the work"},
                            )
                        ],
                    ),
                    Message.assistant("Worker completed the task."),
                ]
            ),
            toolkits=[delegation],
        )

        result = await leader.run(Task(instruction="get this done"))
        assert result.status == TaskStatus.COMPLETED
        assert result.tool_calls_made == 1


class TestGoalValidation:
    def test_too_short(self) -> None:
        from hive.agents.existence import ExistenceLoop

        result = ExistenceLoop._validate_goal("hi", [])
        assert result is not None
        assert "short" in result

    def test_too_long(self) -> None:
        from hive.agents.existence import ExistenceLoop

        result = ExistenceLoop._validate_goal("x" * 600, [])
        assert result is not None
        assert "long" in result

    def test_duplicate_active(self) -> None:
        from hive.agents.existence import ExistenceLoop

        recent = [{"objective": "Learn Python basics", "status": "active"}]
        result = ExistenceLoop._validate_goal("Learn Python basics", recent)
        assert result is not None
        assert "duplicate" in result

    def test_similar_to_abandoned(self) -> None:
        from hive.agents.existence import ExistenceLoop

        recent = [{"objective": "Learn Python programming and write tests", "status": "abandoned"}]
        result = ExistenceLoop._validate_goal(
            "Learn Python programming and write documentation", recent
        )
        assert result is not None
        assert "similar" in result

    def test_valid_goal_passes(self) -> None:
        from hive.agents.existence import ExistenceLoop

        recent = [{"objective": "Something completely different", "status": "completed"}]
        result = ExistenceLoop._validate_goal(
            "Research testing best practices for the team", recent
        )
        assert result is None

    def test_different_goal_passes(self) -> None:
        from hive.agents.existence import ExistenceLoop

        recent = [{"objective": "Learn Python", "status": "abandoned"}]
        result = ExistenceLoop._validate_goal("Write documentation for the API endpoints", recent)
        assert result is None
