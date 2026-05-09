"""Tests for the interactions exchange system."""

from __future__ import annotations

import pytest

from hive.interactions import (
    EnvironmentParticipant,
    ExchangeRunner,
    InteractionMessage,
    Participant,
    agent_chat,
    debate,
    group_discussion,
)
from hive.interactions.base import ExchangeConfig


class MockParticipant:
    """Participant that returns canned responses."""

    def __init__(self, pid: str, name: str, responses: list[str] | None = None):
        self._id = pid
        self._name = name
        self._responses = list(responses or [f"Response from {name}"])
        self._call_count = 0

    @property
    def participant_id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    async def respond(
        self,
        messages: list[InteractionMessage],
        context: str = "",
        system_prompt: str = "",
    ) -> str:
        idx = min(self._call_count, len(self._responses) - 1)
        self._call_count += 1
        return self._responses[idx]


class TestParticipantProtocol:
    def test_mock_satisfies_protocol(self):
        p = MockParticipant("a", "Alice")
        assert isinstance(p, Participant)

    def test_environment_satisfies_protocol(self):
        p = EnvironmentParticipant()
        assert isinstance(p, Participant)


class TestExchangeRunner:
    @pytest.mark.asyncio
    async def test_round_table_basic(self):
        p1 = MockParticipant("a", "Alice", ["Hello from Alice"])
        p2 = MockParticipant("b", "Bob", ["Hello from Bob"])

        config = ExchangeConfig(pattern="round_table", num_rounds=2)
        runner = ExchangeRunner(config)
        result = await runner.run([p1, p2])

        assert result.rounds_completed == 2
        assert len(result.messages) == 4
        assert result.participant_ids == ["a", "b"]

    @pytest.mark.asyncio
    async def test_pairs_basic(self):
        p1 = MockParticipant("a", "Alice")
        p2 = MockParticipant("b", "Bob")

        config = ExchangeConfig(pattern="pairs", num_rounds=1)
        runner = ExchangeRunner(config)
        result = await runner.run([p1, p2])

        assert result.rounds_completed == 1
        assert len(result.messages) == 2

    @pytest.mark.asyncio
    async def test_freeform_basic(self):
        p1 = MockParticipant("a", "Alice")
        p2 = MockParticipant("b", "Bob")
        p3 = MockParticipant("c", "Charlie")

        config = ExchangeConfig(pattern="freeform", num_rounds=1)
        runner = ExchangeRunner(config)
        result = await runner.run([p1, p2, p3])

        assert len(result.messages) == 3

    @pytest.mark.asyncio
    async def test_visibility_round_table(self):
        p1 = MockParticipant("a", "Alice")
        p2 = MockParticipant("b", "Bob")

        config = ExchangeConfig(pattern="round_table", num_rounds=1)
        runner = ExchangeRunner(config)
        result = await runner.run([p1, p2])

        for msg in result.messages:
            assert "a" in msg.visible_to
            assert "b" in msg.visible_to

    @pytest.mark.asyncio
    async def test_visibility_pairs(self):
        p1 = MockParticipant("a", "Alice")
        p2 = MockParticipant("b", "Bob")

        config = ExchangeConfig(pattern="pairs", num_rounds=1)
        runner = ExchangeRunner(config)
        result = await runner.run([p1, p2])

        for msg in result.messages:
            assert len(msg.visible_to) == 2

    @pytest.mark.asyncio
    async def test_topic_passed_to_participants(self):
        received_contexts: list[str] = []

        class CapturingParticipant:
            participant_id = "cap"
            name = "Capturer"

            async def respond(self, messages, context="", system_prompt=""):
                received_contexts.append(context)
                return "ok"

        config = ExchangeConfig(
            pattern="round_table", num_rounds=1, topic="AI ethics",
        )
        runner = ExchangeRunner(config)
        await runner.run([CapturingParticipant()])

        assert "AI ethics" in received_contexts[0]


class TestEnvironmentParticipant:
    @pytest.mark.asyncio
    async def test_no_fn_returns_empty(self):
        env = EnvironmentParticipant()
        result = await env.respond([])
        assert result == ""

    @pytest.mark.asyncio
    async def test_sync_fn(self):
        env = EnvironmentParticipant(
            response_fn=lambda msgs: f"Got {len(msgs)} messages",
        )
        result = await env.respond([
            InteractionMessage(round=0, sender_id="a", sender_name="A", content="hi"),
        ])
        assert result == "Got 1 messages"

    @pytest.mark.asyncio
    async def test_async_fn(self):
        async def my_fn(msgs):
            return f"Async: {len(msgs)}"

        env = EnvironmentParticipant(response_fn=my_fn)
        result = await env.respond([])
        assert result == "Async: 0"


class TestPresets:
    def test_agent_chat(self):
        config = agent_chat(rounds=5, topic="testing")
        assert config.num_rounds == 5
        assert config.topic == "testing"
        assert config.pattern == "round_table"

    def test_group_discussion(self):
        config = group_discussion(rounds=3, topic="design")
        assert config.num_rounds == 3
        assert config.memory_strategy == "selective"

    def test_debate(self):
        config = debate(topic="AI rights")
        assert "debate" in config.context.lower()
        assert config.topic == "AI rights"
