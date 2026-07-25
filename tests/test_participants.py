"""Tests for AgentParticipant, HumanParticipant, and EnvironmentParticipant edge cases."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hive.interactions.base import InteractionMessage
from hive.interactions.participants import (
    AgentParticipant,
    EnvironmentParticipant,
    HumanParticipant,
)
from hive.runtime.types import Message, Role


def _msg(
    round: int, sender_id: str, sender_name: str, content: str, recipient_id: str = "all"
) -> InteractionMessage:
    return InteractionMessage(
        round=round,
        sender_id=sender_id,
        sender_name=sender_name,
        content=content,
        recipient_id=recipient_id,
    )


class TestAgentParticipant:
    def test_properties(self):
        p = AgentParticipant(
            "a1", "Alice", model=MagicMock(), persona="curious", system_prompt="be nice"
        )
        assert p.participant_id == "a1"
        assert p.name == "Alice"

    @pytest.mark.asyncio
    async def test_respond_calls_model(self):
        mock_model = MagicMock()
        mock_model.generate = AsyncMock(
            return_value=Message(role=Role.ASSISTANT, content="  Hello from model!  ")
        )

        p = AgentParticipant("a1", "Alice", model=mock_model, persona="curious detective")
        msgs = [_msg(0, "b1", "Bob", "Hi Alice")]

        result = await p.respond(msgs, context="test topic")
        assert result == "Hello from model!"
        mock_model.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_respond_empty_content(self):
        mock_model = MagicMock()
        mock_model.generate = AsyncMock(return_value=Message(role=Role.ASSISTANT, content=""))

        p = AgentParticipant("a1", "Alice", model=mock_model)
        result = await p.respond([])
        assert result == ""

    @pytest.mark.asyncio
    async def test_respond_none_content(self):
        mock_model = MagicMock()
        mock_model.generate = AsyncMock(return_value=Message(role=Role.ASSISTANT, content=""))

        p = AgentParticipant("a1", "Alice", model=mock_model)
        result = await p.respond([])
        assert result == ""

    @pytest.mark.asyncio
    async def test_respond_uses_system_prompt(self):
        mock_model = MagicMock()
        mock_model.generate = AsyncMock(return_value=Message(role=Role.ASSISTANT, content="ok"))

        p = AgentParticipant("a1", "Alice", model=mock_model, system_prompt="Be helpful")
        await p.respond([], system_prompt="Override prompt")

        call_args = mock_model.generate.call_args
        messages = call_args.kwargs["messages"]
        assert messages[0].role == Role.SYSTEM
        assert messages[0].content == "Override prompt"

    @pytest.mark.asyncio
    async def test_respond_falls_back_to_instance_system_prompt(self):
        mock_model = MagicMock()
        mock_model.generate = AsyncMock(return_value=Message(role=Role.ASSISTANT, content="ok"))

        p = AgentParticipant("a1", "Alice", model=mock_model, system_prompt="Default prompt")
        await p.respond([])

        call_args = mock_model.generate.call_args
        messages = call_args.kwargs["messages"]
        assert messages[0].content == "Default prompt"

    def test_build_prompt_includes_persona(self):
        p = AgentParticipant("a1", "Alice", model=MagicMock(), persona="brilliant detective")
        prompt = p._build_prompt([], "test context")
        assert "brilliant detective" in prompt
        assert "Alice" in prompt

    def test_build_prompt_includes_messages(self):
        p = AgentParticipant("a1", "Alice", model=MagicMock())
        msgs = [
            _msg(0, "b1", "Bob", "Hello"),
            _msg(0, "c1", "Charlie", "Hi there", recipient_id="a1"),
        ]
        prompt = p._build_prompt(msgs, "")
        assert "Bob: Hello" in prompt
        assert "Charlie" in prompt
        assert "→ a1" in prompt

    def test_build_prompt_no_persona(self):
        p = AgentParticipant("a1", "Alice", model=MagicMock())
        prompt = p._build_prompt([], "")
        # Should still have the response instruction
        assert "Respond in character" in prompt


class TestHumanParticipant:
    def test_properties(self):
        p = HumanParticipant()
        assert p.participant_id == "human"
        assert p.name == "Human"

    def test_custom_properties(self):
        p = HumanParticipant(participant_id="h1", name="Player 1")
        assert p.participant_id == "h1"
        assert p.name == "Player 1"

    @pytest.mark.asyncio
    async def test_respond_reads_from_input(self):
        p = HumanParticipant(name="Tester")
        msgs = [_msg(0, "a1", "Alice", "What do you think?")]

        with patch("builtins.input", return_value="I think it's the butler"):
            result = await p.respond(msgs)
        assert result == "I think it's the butler"

    @pytest.mark.asyncio
    async def test_respond_shows_last_messages(self, capsys):
        p = HumanParticipant(name="Tester")
        msgs = [
            _msg(0, "a1", "Alice", "First"),
            _msg(0, "b1", "Bob", "Second"),
            _msg(0, "c1", "Charlie", "Third"),
            _msg(0, "d1", "Dave", "Fourth"),
        ]

        with patch("builtins.input", return_value="ok"):
            await p.respond(msgs)

        captured = capsys.readouterr()
        # Only last 3 messages shown
        assert "First" not in captured.out
        assert "Second" in captured.out
        assert "Third" in captured.out
        assert "Fourth" in captured.out


class TestEnvironmentParticipantEdgeCases:
    @pytest.mark.asyncio
    async def test_error_in_sync_fn_propagates(self):
        def bad_fn(msgs):
            raise ValueError("Something went wrong")

        env = EnvironmentParticipant(response_fn=bad_fn)
        with pytest.raises(ValueError, match="Something went wrong"):
            await env.respond([])

    @pytest.mark.asyncio
    async def test_error_in_async_fn_propagates(self):
        async def bad_fn(msgs):
            raise RuntimeError("Async error")

        env = EnvironmentParticipant(response_fn=bad_fn)
        with pytest.raises(RuntimeError, match="Async error"):
            await env.respond([])

    @pytest.mark.asyncio
    async def test_non_string_return_coerced(self):
        env = EnvironmentParticipant(response_fn=lambda msgs: 42)
        result = await env.respond([])
        assert result == "42"

    @pytest.mark.asyncio
    async def test_context_and_system_prompt_ignored(self):
        """EnvironmentParticipant ignores context and system_prompt."""
        received_msgs = []

        def capture(msgs):
            received_msgs.extend(msgs)
            return "ok"

        env = EnvironmentParticipant(response_fn=capture)
        msg = _msg(0, "a", "A", "hello")
        await env.respond([msg], context="ignored", system_prompt="also ignored")

        assert len(received_msgs) == 1
        assert received_msgs[0].content == "hello"
