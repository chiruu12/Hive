"""Tests for legacy interaction patterns: RoundTablePattern, PairsPattern, FreeformPattern."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from hive.interactions.base import AgentSlot, Message, RoundResult
from hive.interactions.patterns.freeform import FreeformPattern
from hive.interactions.patterns.pairs import PairsPattern
from hive.interactions.patterns.round_table import RoundTablePattern
from hive.models.base import GenerateResult


def _slot(slot_id: str, name: str = "", model: str = "test-model") -> AgentSlot:
    return AgentSlot(
        slot_id=slot_id,
        name=name or slot_id.title(),
        model=model,
        system_prompt=f"You are {slot_id}",
    )


def _generate_result(
    content: str, input_tokens: int = 10, output_tokens: int = 5
) -> GenerateResult:
    from hive.runtime.types import Message as RuntimeMessage
    from hive.runtime.types import Role

    return GenerateResult(
        message=RuntimeMessage(role=Role.ASSISTANT, content=content),
        model="test",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=0.001,
    )


def _mock_provider_factory(responses: dict[str, list[str]] | None = None):
    """Create a provider_factory that returns mock providers per model."""
    responses = responses or {}
    providers: dict[str, MagicMock] = {}

    def factory(model: str) -> MagicMock:
        if model not in providers:
            provider = MagicMock()
            call_count = [0]
            model_responses = responses.get(model, ["Default response"])

            async def generate(*args, **kwargs):
                idx = min(call_count[0], len(model_responses) - 1)
                call_count[0] += 1
                return _generate_result(model_responses[idx])

            provider.generate_with_metadata = AsyncMock(side_effect=generate)
            providers[model] = provider
        return providers[model]

    return factory


def _context_builder(agent: AgentSlot, visible: list[Message], round_num: int) -> str:
    return f"Round {round_num}: {len(visible)} visible messages for {agent.slot_id}"


# ---------------------------------------------------------------------------
# RoundTablePattern
# ---------------------------------------------------------------------------


class TestRoundTablePattern:
    @pytest.mark.asyncio
    async def test_basic_round(self):
        pattern = RoundTablePattern()
        agents = [_slot("alice"), _slot("bob")]
        factory = _mock_provider_factory({"test-model": ["Hello", "Hi there"]})

        result = await pattern.run_round(agents, 0, [], _context_builder, factory)

        assert isinstance(result, RoundResult)
        assert result.round_num == 0
        assert len(result.messages) == 2
        assert result.messages[0].sender == "alice"
        assert result.messages[1].sender == "bob"

    @pytest.mark.asyncio
    async def test_all_visible_to_all(self):
        pattern = RoundTablePattern()
        agents = [_slot("alice"), _slot("bob"), _slot("charlie")]
        factory = _mock_provider_factory()

        result = await pattern.run_round(agents, 0, [], _context_builder, factory)

        for msg in result.messages:
            assert set(msg.visible_to) == {"alice", "bob", "charlie"}

    @pytest.mark.asyncio
    async def test_subsequent_rounds_see_history(self):
        pattern = RoundTablePattern()
        agents = [_slot("alice"), _slot("bob")]
        factory = _mock_provider_factory()

        r0 = await pattern.run_round(agents, 0, [], _context_builder, factory)
        r1 = await pattern.run_round(agents, 1, [r0], _context_builder, factory)

        assert len(r1.messages) == 2
        # Provider should have been called with context showing visible history
        provider = factory("test-model")
        assert provider.generate_with_metadata.call_count == 4  # 2 per round

    @pytest.mark.asyncio
    async def test_recipient_is_all(self):
        pattern = RoundTablePattern()
        agents = [_slot("alice")]
        factory = _mock_provider_factory()

        result = await pattern.run_round(agents, 0, [], _context_builder, factory)
        assert result.messages[0].recipient == "all"

    @pytest.mark.asyncio
    async def test_get_visible_messages(self):
        pattern = RoundTablePattern()
        history = [
            RoundResult(
                round_num=0,
                messages=[
                    Message(round=0, sender="alice", content="hi", visible_to=["alice", "bob"]),
                    Message(round=0, sender="bob", content="hello", visible_to=["alice", "bob"]),
                ],
            ),
            RoundResult(
                round_num=1,
                messages=[
                    Message(round=1, sender="alice", content="secret", visible_to=["alice"]),
                ],
            ),
        ]

        visible = pattern.get_visible_messages("alice", history)
        assert len(visible) == 3

        visible_bob = pattern.get_visible_messages("bob", history)
        assert len(visible_bob) == 2  # Bob can't see the alice-only message

    @pytest.mark.asyncio
    async def test_get_visible_messages_empty_visible_to(self):
        pattern = RoundTablePattern()
        history = [
            RoundResult(
                round_num=0,
                messages=[
                    Message(round=0, sender="system", content="announcement", visible_to=[]),
                ],
            ),
        ]
        visible = pattern.get_visible_messages("anyone", history)
        assert len(visible) == 1  # empty visible_to means everyone can see


# ---------------------------------------------------------------------------
# PairsPattern
# ---------------------------------------------------------------------------


class TestPairsPattern:
    @pytest.mark.asyncio
    async def test_basic_pair(self):
        pattern = PairsPattern()
        agents = [_slot("alice"), _slot("bob")]
        factory = _mock_provider_factory()

        result = await pattern.run_round(agents, 0, [], _context_builder, factory)

        assert len(result.messages) == 2  # Each speaks once
        # Messages should be between the paired agents
        senders = {m.sender for m in result.messages}
        assert senders == {"alice", "bob"}

    @pytest.mark.asyncio
    async def test_pair_messages_private(self):
        pattern = PairsPattern()
        agents = [_slot("alice"), _slot("bob")]
        factory = _mock_provider_factory()

        result = await pattern.run_round(agents, 0, [], _context_builder, factory)

        for msg in result.messages:
            assert len(msg.visible_to) == 2

    @pytest.mark.asyncio
    async def test_four_agents_two_pairs(self):
        pattern = PairsPattern()
        agents = [_slot("a"), _slot("b"), _slot("c"), _slot("d")]
        factory = _mock_provider_factory()

        result = await pattern.run_round(agents, 0, [], _context_builder, factory)

        assert len(result.messages) == 4  # 2 pairs × 2 speakers

    @pytest.mark.asyncio
    async def test_odd_count_pairs_leftover(self):
        pattern = PairsPattern()
        agents = [_slot("a"), _slot("b"), _slot("c")]
        factory = _mock_provider_factory()

        result = await pattern.run_round(agents, 0, [], _context_builder, factory)

        # 3 agents: 1 pair (2 msgs) + leftover paired with first of last pair (2 msgs) = 4
        assert len(result.messages) == 4

    @pytest.mark.asyncio
    async def test_single_agent_no_pairs(self):
        pattern = PairsPattern()
        agents = [_slot("lonely")]
        factory = _mock_provider_factory()

        result = await pattern.run_round(agents, 0, [], _context_builder, factory)
        assert len(result.messages) == 0

    @pytest.mark.asyncio
    async def test_deterministic_pairing(self):
        pattern = PairsPattern()
        agents = [_slot("a"), _slot("b"), _slot("c"), _slot("d")]

        pairs1 = pattern._make_pairs(agents, 0)
        pairs2 = pattern._make_pairs(agents, 0)
        assert pairs1 == pairs2

    @pytest.mark.asyncio
    async def test_different_rounds_different_pairings(self):
        pattern = PairsPattern()
        agents = [_slot("a"), _slot("b"), _slot("c"), _slot("d")]

        pairings = set()
        for r in range(10):
            pairs = pattern._make_pairs(agents, r)
            pairing = frozenset((a.slot_id, b.slot_id) for a, b in pairs)
            pairings.add(pairing)

        # With 4 agents, there are 3 possible pairings; over 10 rounds we should see >1
        assert len(pairings) > 1

    def test_get_visible_messages(self):
        pattern = PairsPattern()
        history = [
            RoundResult(
                round_num=0,
                messages=[
                    Message(round=0, sender="alice", content="to bob", visible_to=["alice", "bob"]),
                    Message(
                        round=0, sender="charlie", content="to dave", visible_to=["charlie", "dave"]
                    ),
                ],
            ),
        ]

        visible_alice = pattern.get_visible_messages("alice", history)
        assert len(visible_alice) == 1
        assert visible_alice[0].content == "to bob"


# ---------------------------------------------------------------------------
# FreeformPattern
# ---------------------------------------------------------------------------


class TestFreeformPattern:
    @pytest.mark.asyncio
    async def test_basic_round(self):
        pattern = FreeformPattern()
        agents = [_slot("alice"), _slot("bob")]
        factory = _mock_provider_factory(
            {"test-model": ['{"to": "all", "message": "Hello everyone"}']}
        )

        result = await pattern.run_round(agents, 0, [], _context_builder, factory)

        assert len(result.messages) == 2
        assert result.messages[0].sender == "alice"

    @pytest.mark.asyncio
    async def test_whisper_to_specific_agent(self):
        pattern = FreeformPattern()
        agents = [_slot("alice"), _slot("bob")]
        factory = _mock_provider_factory(
            {"test-model": ['{"to": "bob", "message": "Psst, secret"}']}
        )

        result = await pattern.run_round(agents, 0, [], _context_builder, factory)

        msg = result.messages[0]
        assert msg.recipient == "bob"
        assert msg.visible_to == ["alice", "bob"]

    @pytest.mark.asyncio
    async def test_broadcast_to_all(self):
        pattern = FreeformPattern()
        agents = [_slot("alice"), _slot("bob")]
        factory = _mock_provider_factory({"test-model": ['{"to": "all", "message": "Public msg"}']})

        result = await pattern.run_round(agents, 0, [], _context_builder, factory)

        msg = result.messages[0]
        assert msg.recipient == "all"
        assert set(msg.visible_to) == {"alice", "bob"}

    @pytest.mark.asyncio
    async def test_fallback_on_plain_text(self):
        pattern = FreeformPattern()
        agents = [_slot("alice")]
        factory = _mock_provider_factory({"test-model": ["Just plain text, no JSON"]})

        result = await pattern.run_round(agents, 0, [], _context_builder, factory)

        msg = result.messages[0]
        assert msg.recipient == "all"
        assert "Just plain text" in msg.content

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_json(self):
        pattern = FreeformPattern()
        agents = [_slot("alice")]
        factory = _mock_provider_factory({"test-model": ['{"to": "bob", "message": invalid json}']})

        result = await pattern.run_round(agents, 0, [], _context_builder, factory)
        assert result.messages[0].recipient == "all"

    @pytest.mark.asyncio
    async def test_fallback_on_unknown_recipient(self):
        pattern = FreeformPattern()
        agents = [_slot("alice"), _slot("bob")]
        factory = _mock_provider_factory(
            {"test-model": ['{"to": "unknown_agent", "message": "hello"}']}
        )

        result = await pattern.run_round(agents, 0, [], _context_builder, factory)
        assert result.messages[0].recipient == "all"

    @pytest.mark.asyncio
    async def test_strips_markdown_code_fences(self):
        pattern = FreeformPattern()
        agents = [_slot("alice")]
        factory = _mock_provider_factory(
            {"test-model": ['```json\n{"to": "all", "message": "stripped"}\n```']}
        )

        result = await pattern.run_round(agents, 0, [], _context_builder, factory)
        assert "stripped" in result.messages[0].content

    @pytest.mark.asyncio
    async def test_strips_think_tags(self):
        pattern = FreeformPattern()
        agents = [_slot("alice")]
        factory = _mock_provider_factory(
            {
                "test-model": [
                    '<think>Let me think...</think>\n{"to": "all", "message": "after think"}'
                ]
            }
        )

        result = await pattern.run_round(agents, 0, [], _context_builder, factory)
        assert "after think" in result.messages[0].content

    @pytest.mark.asyncio
    async def test_invalid_agent_id_defaults_to_all(self):
        pattern = FreeformPattern()
        agents = [_slot("alice"), _slot("bob")]
        factory = _mock_provider_factory(
            {"test-model": ['{"to": "charlie", "message": "wrong id"}']}
        )

        result = await pattern.run_round(agents, 0, [], _context_builder, factory)
        assert result.messages[0].recipient == "all"

    def test_get_visible_messages(self):
        pattern = FreeformPattern()
        history = [
            RoundResult(
                round_num=0,
                messages=[
                    Message(
                        round=0, sender="alice", content="whisper", visible_to=["alice", "bob"]
                    ),
                    Message(
                        round=0,
                        sender="charlie",
                        content="broadcast",
                        visible_to=["alice", "bob", "charlie"],
                    ),
                ],
            ),
        ]

        visible = pattern.get_visible_messages("alice", history)
        assert len(visible) == 2

        visible_dave = pattern.get_visible_messages("dave", history)
        assert len(visible_dave) == 0
