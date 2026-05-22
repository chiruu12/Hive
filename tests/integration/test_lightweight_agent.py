"""Integration test: lightweight agent pattern (Mutter's usage).

Simulates how Mutter creates reusable toolkits at startup and
lightweight agents per request via run_once().
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from hive.memory.store import HiveStore
from hive.runtime.agent import Agent
from hive.runtime.types import GenerateResult, Message, Role, ToolCall
from hive.tools.alarms.toolkit import AlarmToolkit
from hive.tools.knowledge.toolkit import KnowledgeToolkit
from hive.tools.tasks.toolkit import TaskToolkit


class MockProvider:
    """Minimal mock provider that returns pre-programmed tool calls."""

    def __init__(self, responses: list[Message]):
        self._responses = list(responses)
        self._model = "mock-model"
        self._call_idx = 0

    @property
    def model(self) -> str:
        return self._model

    @property
    def available(self) -> bool:
        return True

    async def generate_with_metadata(self, messages, tools=None, temperature=0.0, max_tokens=4096):
        msg = self._responses[self._call_idx % len(self._responses)]
        self._call_idx += 1
        return GenerateResult(
            message=msg,
            model=self._model,
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
            duration_ms=50,
        )

    async def generate_structured(self, messages, output_type, temperature=0.0, max_tokens=4096):
        raise NotImplementedError


@pytest.fixture
async def store(tmp_path: Path) -> HiveStore:
    s = HiveStore(tmp_path / "app.db")
    await s.initialize()
    return s


@pytest.fixture
def task_tk(store) -> TaskToolkit:
    tk = TaskToolkit(store=store)
    tk.bind("mutter")
    return tk


@pytest.fixture
def alarm_tk(store) -> AlarmToolkit:
    tk = AlarmToolkit(store=store)
    tk.bind("mutter")
    return tk


@pytest.fixture
def knowledge_tk(tmp_path) -> KnowledgeToolkit:
    tk = KnowledgeToolkit(memory_dir=tmp_path / "knowledge")
    tk.bind("mutter")
    return tk


class TestLightweightAgent:
    @pytest.mark.asyncio
    async def test_create_task_via_agent(self, task_tk, store):
        provider = MockProvider(
            [
                Message(
                    role=Role.ASSISTANT,
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="tc1",
                            name="create_task",
                            arguments={"description": "Buy groceries", "priority": "medium"},
                        )
                    ],
                ),
                Message(role=Role.ASSISTANT, content="Done! Created a task for buying groceries."),
            ]
        )
        agent = Agent(name="mutter", model=provider, toolkits=[task_tk])
        result = await agent.run_once("create a task: buy groceries")
        assert "groceries" in result.lower() or "done" in result.lower()

        tasks = await store.list_tasks("mutter", "pending")
        assert len(tasks) == 1
        assert tasks[0]["description"] == "Buy groceries"

    @pytest.mark.asyncio
    async def test_set_alarm_via_agent(self, alarm_tk, store):
        provider = MockProvider(
            [
                Message(
                    role=Role.ASSISTANT,
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="tc1",
                            name="set_alarm",
                            arguments={"description": "Stand up", "minutes": 30},
                        )
                    ],
                ),
                Message(role=Role.ASSISTANT, content="Alarm set for 30 minutes."),
            ]
        )
        agent = Agent(name="mutter", model=provider, toolkits=[alarm_tk])
        result = await agent.run_once("set an alarm for 30 minutes")
        assert "alarm" in result.lower() or "30" in result

        alarms = await store.list_pending_alarms("mutter")
        assert len(alarms) == 1
        assert "Stand up" in alarms[0]["description"]

    @pytest.mark.asyncio
    async def test_save_note_via_agent(self, knowledge_tk):
        provider = MockProvider(
            [
                Message(
                    role=Role.ASSISTANT,
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="tc1",
                            name="save_note",
                            arguments={
                                "content": "Meeting with team went well",
                                "tags": "meetings",
                            },
                        )
                    ],
                ),
                Message(role=Role.ASSISTANT, content="Note saved."),
            ]
        )
        agent = Agent(name="mutter", model=provider, toolkits=[knowledge_tk])
        result = await agent.run_once("save a note: meeting with team went well")
        assert "saved" in result.lower() or "note" in result.lower()

    @pytest.mark.asyncio
    async def test_multi_tool_call(self, task_tk, alarm_tk, store):
        provider = MockProvider(
            [
                Message(
                    role=Role.ASSISTANT,
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="tc1",
                            name="create_task",
                            arguments={"description": "Finish report", "priority": "high"},
                        ),
                        ToolCall(
                            id="tc2",
                            name="set_alarm",
                            arguments={"description": "Reminder: finish report", "hours": 1},
                        ),
                    ],
                ),
                Message(role=Role.ASSISTANT, content="Created task and set reminder."),
            ]
        )
        agent = Agent(name="mutter", model=provider, toolkits=[task_tk, alarm_tk])
        await agent.run_once("create a task and set a reminder for it")

        tasks = await store.list_tasks("mutter", "pending")
        assert any("report" in t["description"].lower() for t in tasks)

        alarms = await store.list_pending_alarms("mutter")
        assert any("report" in a["description"].lower() for a in alarms)

    @pytest.mark.asyncio
    async def test_toolkit_reusability(self, task_tk, store):
        """Verify no state leaks across multiple run_once calls."""
        for i in range(5):
            provider = MockProvider(
                [
                    Message(
                        role=Role.ASSISTANT,
                        content="",
                        tool_calls=[
                            ToolCall(
                                id=f"tc{i}",
                                name="create_task",
                                arguments={"description": f"Task {i}", "priority": "medium"},
                            )
                        ],
                    ),
                    Message(role=Role.ASSISTANT, content=f"Created task {i}."),
                ]
            )
            agent = Agent(name="mutter", model=provider, toolkits=[task_tk])
            await agent.run_once(f"create task {i}")

        tasks = await store.list_tasks("mutter", "pending")
        assert len(tasks) == 5

    def test_agent_creation_overhead(self, task_tk, alarm_tk, knowledge_tk):
        """Agent constructor should be fast (<50ms)."""
        provider = MockProvider([Message(role=Role.ASSISTANT, content="ok")])

        start = time.perf_counter()
        for _ in range(100):
            Agent(
                name="mutter",
                model=provider,
                toolkits=[task_tk, alarm_tk, knowledge_tk],
            )
        elapsed = (time.perf_counter() - start) / 100

        assert elapsed < 0.05, f"Agent creation took {elapsed*1000:.1f}ms (limit: 50ms)"
