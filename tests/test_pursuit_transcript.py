"""Phase C pursuit transcript persistence and resume."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hive.memory.pursuit_transcript import (
    PursuitTranscriptStore,
    message_from_dict,
    message_to_dict,
    messages_match,
    truncate_messages,
)
from hive.memory.store import HiveStore
from hive.models.base import BaseProvider
from hive.runtime import Agent, DaemonAgentAdapter
from hive.runtime.types import GenerateResult, Message, ToolCall
from hive.tools.base import Toolkit, tool


class _NoopToolkit(Toolkit):
    @tool()
    async def noop(self) -> str:
        """No-op tool."""
        return "tool-ok-cycle-marker"


class _LoopingProvider(BaseProvider):
    """Always requests a tool until max_steps."""

    def __init__(self) -> None:
        super().__init__("mock-loop")
        self.calls = 0
        self.seen_messages: list[list[Message]] = []

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
        self.calls += 1
        self.seen_messages.append(list(messages))
        if tools:
            return GenerateResult(
                message=Message.assistant(
                    "working",
                    [ToolCall(id=f"tc-{self.calls}", name="noop", arguments={})],
                ),
                model="mock-loop",
            )
        return GenerateResult(message=Message.assistant("done"), model="mock-loop")


class _CompletingProvider(BaseProvider):
    """Loops on first slice; completes when prior tool result is visible on resume."""

    MARKER = "tool-ok-cycle-marker"

    def __init__(self) -> None:
        super().__init__("mock-resume")
        self.calls = 0
        self.seen_messages: list[list[Message]] = []

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
        self.calls += 1
        self.seen_messages.append(list(messages))
        resumed = any(
            m.role.value == "system" and "updated pursuit context" in m.content.lower()
            for m in messages
        )
        transcript = " ".join(m.content for m in messages)
        if resumed and self.MARKER in transcript:
            return GenerateResult(message=Message.assistant("finished after resume"), model="mock")
        if tools:
            return GenerateResult(
                message=Message.assistant(
                    "call tool",
                    [ToolCall(id=f"tc-{self.calls}", name="noop", arguments={})],
                ),
                model="mock",
            )
        return GenerateResult(message=Message.assistant("done"), model="mock")


def test_message_round_trip() -> None:
    original = Message.assistant(
        "hi",
        [ToolCall(id="tc-1", name="noop", arguments={"x": 1})],
    )
    restored = message_from_dict(message_to_dict(original))
    assert restored.role == original.role
    assert restored.content == original.content
    assert len(restored.tool_calls) == 1
    assert restored.tool_calls[0].name == "noop"


def test_messages_match() -> None:
    a = [Message.user("hello"), Message.assistant("hi")]
    b = [Message.user("hello"), Message.assistant("hi")]
    c = [Message.user("hello"), Message.assistant("bye")]
    assert messages_match(a, b)
    assert not messages_match(a, c)
    assert not messages_match(a, a[:1])


@pytest.mark.asyncio
async def test_bridge_resume_at_cap_persists_new_turns(tmp_path: Path) -> None:
    """Near-cap archive must persist new turns after resume, not silent no-op delta."""
    store = HiveStore(tmp_path / "hive.db")
    await store.initialize()
    max_messages = 20
    transcript = PursuitTranscriptStore(store, max_messages=max_messages)
    archived = [Message.user(f"msg-{i}") for i in range(max_messages)]
    await transcript.save_messages("goal-cap", "agent-1", archived)
    assert len(await transcript.load_messages("goal-cap", "agent-1")) == max_messages

    provider = _LoopingProvider()
    agent = Agent(name="tester", model=provider, toolkits=[_NoopToolkit()], max_steps=2)
    adapter = DaemonAgentAdapter(agent, "agent-1")

    outcome = await adapter.pursue_goal(
        "Keep working",
        context="cycle-at-cap",
        goal_id="goal-cap",
        transcript_store=transcript,
    )
    assert outcome.hit_step_limit is True

    loaded = await transcript.load_messages("goal-cap", "agent-1")
    assert len(loaded) == max_messages
    contents = " ".join(m.content for m in loaded)
    assert _CompletingProvider.MARKER in contents
    assert "cycle-at-cap" in contents
    assert any(m.role.value == "tool" for m in loaded)
    assert all(m.content.startswith("msg-") for m in archived)
    assert not all(m.content.startswith("msg-") for m in loaded)


def test_truncate_messages_preserves_tool_groups() -> None:
    msgs = [
        Message.user("start"),
        Message.assistant("a", [ToolCall(id="1", name="t", arguments={})]),
        Message.tool_result("1", "result"),
        Message.user("more"),
    ]
    capped = truncate_messages(msgs, max_messages=4)
    assert len(capped) == 4
    capped_tight = truncate_messages(msgs, max_messages=2)
    assert len(capped_tight) <= 2


@pytest.mark.asyncio
async def test_store_save_load_delete(tmp_path: Path) -> None:
    store = HiveStore(tmp_path / "hive.db")
    await store.initialize()
    transcript = PursuitTranscriptStore(store, max_messages=50)
    goal_id = "goal-abc"
    messages = [
        Message.user("do work"),
        Message.assistant("ok", [ToolCall(id="tc-1", name="noop", arguments={})]),
        Message.tool_result("tc-1", "tool-ok-cycle-marker"),
    ]
    await transcript.save_messages(goal_id, "agent-1", messages)

    loaded = await transcript.load_messages(goal_id, "agent-1")
    assert len(loaded) == 3
    assert loaded[-1].content == "tool-ok-cycle-marker"

    await transcript.delete_transcript(goal_id)
    assert await transcript.load_messages(goal_id, "agent-1") == []


@pytest.mark.asyncio
async def test_bridge_persists_transcript_on_max_steps(tmp_path: Path) -> None:
    store = HiveStore(tmp_path / "hive.db")
    await store.initialize()
    transcript = PursuitTranscriptStore(store)
    provider = _LoopingProvider()
    agent = Agent(name="tester", model=provider, toolkits=[_NoopToolkit()], max_steps=2)
    adapter = DaemonAgentAdapter(agent, "agent-1")

    outcome = await adapter.pursue_goal(
        "Keep working",
        goal_id="goal-1",
        transcript_store=transcript,
    )
    assert outcome.hit_step_limit is True
    assert outcome.steps_done == 2

    saved = await transcript.load_messages("goal-1", "agent-1")
    assert saved
    assert any(m.role.value == "tool" for m in saved)


@pytest.mark.asyncio
async def test_bridge_resume_replays_prior_tool_results(tmp_path: Path) -> None:
    store = HiveStore(tmp_path / "hive.db")
    await store.initialize()
    transcript = PursuitTranscriptStore(store)
    provider = _CompletingProvider()
    agent = Agent(name="tester", model=provider, toolkits=[_NoopToolkit()], max_steps=2)
    adapter = DaemonAgentAdapter(agent, "agent-1")

    first = await adapter.pursue_goal(
        "Multi-step task",
        context="cycle-1",
        goal_id="goal-resume",
        transcript_store=transcript,
    )
    assert first.hit_step_limit is True

    provider.calls = 0
    provider.seen_messages.clear()
    second = await adapter.pursue_goal(
        "Multi-step task",
        context="cycle-2",
        goal_id="goal-resume",
        transcript_store=transcript,
    )
    assert second.success is True
    assert provider.calls >= 1
    first_turn = provider.seen_messages[0]
    tool_contents = [m.content for m in first_turn if m.role.value == "tool"]
    assert _CompletingProvider.MARKER in " ".join(tool_contents)


@pytest.mark.asyncio
async def test_complete_goal_clears_transcript(tmp_path: Path) -> None:
    store = HiveStore(tmp_path / "hive.db")
    await store.initialize()
    await store.save_goal("goal-done", "agent-1", "finish me")
    transcript = PursuitTranscriptStore(store)
    await transcript.save_messages("goal-done", "agent-1", [Message.user("work")])

    await store.complete_goal("goal-done")
    assert await transcript.load_messages("goal-done", "agent-1") == []


@pytest.mark.asyncio
async def test_pursuit_resume_disabled_skips_load(tmp_path: Path) -> None:
    store = HiveStore(tmp_path / "hive.db")
    await store.initialize()
    transcript = PursuitTranscriptStore(store)
    await transcript.save_messages(
        "goal-off",
        "agent-1",
        [Message.user("prior"), Message.tool_result("tc-1", "tool-ok-cycle-marker")],
    )

    provider = _LoopingProvider()
    agent = Agent(name="tester", model=provider, toolkits=[_NoopToolkit()], max_steps=2)
    adapter = DaemonAgentAdapter(agent, "agent-1")

    outcome = await adapter.pursue_goal(
        "Fresh task",
        goal_id="goal-off",
        resume=False,
        transcript_store=transcript,
    )
    assert outcome.hit_step_limit is True
    assert provider.calls == 2
    first_turn = provider.seen_messages[0]
    tool_contents = [m.content for m in first_turn if m.role.value == "tool"]
    assert "tool-ok-cycle-marker" not in " ".join(tool_contents)


@pytest.mark.asyncio
async def test_abandon_goal_clears_transcript(tmp_path: Path) -> None:
    store = HiveStore(tmp_path / "hive.db")
    await store.initialize()
    await store.save_goal("goal-abandon", "agent-1", "drop me")
    transcript = PursuitTranscriptStore(store)
    await transcript.save_messages("goal-abandon", "agent-1", [Message.user("work")])

    await store.abandon_goal("goal-abandon")
    assert await transcript.load_messages("goal-abandon", "agent-1") == []


@pytest.mark.asyncio
async def test_resume_does_not_shrink_transcript_below_store_cap(tmp_path: Path) -> None:
    """Resume must not rewrite archive with max_steps*4 in-memory cap."""
    store = HiveStore(tmp_path / "hive.db")
    await store.initialize()
    await store.save_goal("goal-shrink", "agent-1", "long pursuit")
    transcript = PursuitTranscriptStore(store, max_messages=200)
    archived = [Message.user(f"msg-{i}") for i in range(15)]
    await transcript.save_messages("goal-shrink", "agent-1", archived)

    provider = _LoopingProvider()
    agent = Agent(name="tester", model=provider, toolkits=[_NoopToolkit()], max_steps=2)
    adapter = DaemonAgentAdapter(agent, "agent-1")

    outcome = await adapter.pursue_goal(
        "Keep working",
        goal_id="goal-shrink",
        transcript_store=transcript,
    )
    assert outcome.hit_step_limit is True

    loaded = await transcript.load_messages("goal-shrink", "agent-1")
    assert len(loaded) >= 15
    assert loaded[0].content == "msg-0"


@pytest.mark.asyncio
async def test_cross_agent_cannot_load_transcript_by_goal_id(tmp_path: Path) -> None:
    store = HiveStore(tmp_path / "hive.db")
    await store.initialize()
    await store.save_goal("goal-isolated", "agent-1", "private")
    transcript = PursuitTranscriptStore(store)
    await transcript.save_messages(
        "goal-isolated",
        "agent-1",
        [Message.user("agent-1 secret")],
    )

    assert await transcript.load_messages("goal-isolated", "agent-1")
    assert await transcript.load_messages("goal-isolated", "agent-2") == []

    with pytest.raises(ValueError, match="belongs to agent"):
        await transcript.save_messages(
            "goal-isolated",
            "agent-2",
            [Message.user("hostile overwrite")],
        )


@pytest.mark.asyncio
async def test_poison_transcript_row_soft_fails(tmp_path: Path) -> None:
    store = HiveStore(tmp_path / "hive.db")
    await store.initialize()
    await store.save_goal("goal-poison", "agent-1", "tolerate bad rows")
    transcript = PursuitTranscriptStore(store)
    good = Message.user("valid")
    await transcript.save_messages("goal-poison", "agent-1", [good])

    async with store._connect() as db:
        await db.execute(
            """INSERT INTO pursuit_transcripts
               (goal_id, agent_id, seq, message_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("goal-poison", "agent-1", 99, "{not-json", "2026-01-01T00:00:00+00:00"),
        )
        await db.execute(
            """INSERT INTO pursuit_transcripts
               (goal_id, agent_id, seq, message_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "goal-poison",
                "agent-1",
                100,
                '{"role": "invalid_role", "content": "bad"}',
                "2026-01-01T00:00:00+00:00",
            ),
        )
        await db.commit()

    loaded = await transcript.load_messages("goal-poison", "agent-1")
    assert len(loaded) == 1
    assert loaded[0].content == "valid"
