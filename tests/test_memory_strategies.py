"""Tests for interaction memory strategies: FullMemory, SelectiveMemory, PersonaMemory."""

from __future__ import annotations

from hive.interactions.base import AgentSlot, Message
from hive.interactions.memory.full import FullMemory
from hive.interactions.memory.persona import PersonaMemory
from hive.interactions.memory.selective import SelectiveMemory


def _slot(
    slot_id: str = "alice", persona: str = "curious detective", role: str = "investigator"
) -> AgentSlot:
    return AgentSlot(
        slot_id=slot_id, name=slot_id.title(), model="test", persona=persona, role=role
    )


def _msg(
    round: int,
    sender: str,
    content: str,
    recipient: str = "all",
    visible_to: list[str] | None = None,
) -> Message:
    return Message(
        round=round,
        sender=sender,
        content=content,
        recipient=recipient,
        visible_to=visible_to or [],
    )


# ---------------------------------------------------------------------------
# FullMemory
# ---------------------------------------------------------------------------


class TestFullMemory:
    def test_empty_returns_placeholder(self):
        mem = FullMemory()
        result = mem.build_context(_slot(), [], 0)
        assert result == "No messages yet."

    def test_all_messages_shown(self):
        mem = FullMemory()
        msgs = [
            _msg(0, "alice", "Hello"),
            _msg(0, "bob", "Hi there"),
            _msg(1, "alice", "What do you think?"),
        ]
        result = mem.build_context(_slot(), msgs, 1)
        assert "Hello" in result
        assert "Hi there" in result
        assert "What do you think?" in result

    def test_format_includes_round_and_sender(self):
        mem = FullMemory()
        msgs = [_msg(2, "bob", "Interesting point")]
        result = mem.build_context(_slot(), msgs, 2)
        assert "[Round 2] bob" in result

    def test_directed_message_shows_arrow(self):
        mem = FullMemory()
        msgs = [_msg(0, "bob", "Secret info", recipient="alice")]
        result = mem.build_context(_slot(), msgs, 0)
        assert "→ alice" in result

    def test_broadcast_no_arrow(self):
        mem = FullMemory()
        msgs = [_msg(0, "bob", "Public info", recipient="all")]
        result = mem.build_context(_slot(), msgs, 0)
        assert "→" not in result


# ---------------------------------------------------------------------------
# SelectiveMemory
# ---------------------------------------------------------------------------


class TestSelectiveMemory:
    def test_empty_returns_placeholder(self):
        mem = SelectiveMemory()
        result = mem.build_context(_slot("alice"), [], 0)
        assert result == "No messages yet."

    def test_own_messages_verbatim(self):
        mem = SelectiveMemory()
        alice = _slot("alice")
        msgs = [
            _msg(0, "alice", "I believe the suspect is guilty"),
            _msg(0, "bob", "I disagree completely"),
        ]
        result = mem.build_context(alice, msgs, 0)
        assert "I believe the suspect is guilty" in result
        assert "You said:" in result

    def test_others_messages_summarized(self):
        mem = SelectiveMemory()
        alice = _slot("alice")
        msgs = [
            _msg(0, "bob", "The extraordinary evidence suggests otherwise"),
            _msg(0, "charlie", "I have extraordinary proof"),
        ]
        result = mem.build_context(alice, msgs, 0)
        # Long words (>5 chars) are extracted as topics
        assert "discussed:" in result
        assert "extraordinary" in result

    def test_no_own_messages_no_statement_section(self):
        mem = SelectiveMemory()
        alice = _slot("alice")
        msgs = [_msg(0, "bob", "Hello everyone")]
        result = mem.build_context(alice, msgs, 0)
        assert "Your previous statements:" not in result

    def test_multiple_rounds_grouped(self):
        mem = SelectiveMemory()
        alice = _slot("alice")
        msgs = [
            _msg(0, "bob", "Round zero message here"),
            _msg(1, "charlie", "Round one message here"),
            _msg(2, "bob", "Round two message here"),
        ]
        result = mem.build_context(alice, msgs, 2)
        assert "[Round 0]" in result
        assert "[Round 1]" in result
        assert "[Round 2]" in result

    def test_own_messages_limited_to_10(self):
        mem = SelectiveMemory()
        alice = _slot("alice")
        msgs = [_msg(i, "alice", f"Message number {i}") for i in range(15)]
        result = mem.build_context(alice, msgs, 14)
        # Only last 10 should appear
        assert "Message number 14" in result
        assert "Message number 5" in result
        assert "Message number 4" not in result


# ---------------------------------------------------------------------------
# PersonaMemory
# ---------------------------------------------------------------------------


class TestPersonaMemory:
    def test_empty_returns_placeholder(self):
        mem = PersonaMemory()
        result = mem.build_context(_slot(), [], 0)
        assert result == "No messages yet."

    def test_own_messages_always_relevant(self):
        mem = PersonaMemory()
        alice = _slot("alice", persona="detective investigating murder")
        msgs = [_msg(0, "alice", "Completely unrelated text")]
        result = mem.build_context(alice, msgs, 0)
        assert "Completely unrelated text" in result

    def test_persona_overlap_boosts_relevance(self):
        mem = PersonaMemory()
        alice = _slot("alice", persona="curious detective solving mysteries")
        msgs = [
            _msg(0, "bob", "The detective found mysterious clues"),
            _msg(0, "charlie", "Weather is nice today"),
        ]
        result = mem.build_context(alice, msgs, 0)
        # "detective" and "mysterious" overlap with persona tokens
        lines = result.split("\n")
        # The detective-related message should come first (higher relevance)
        assert "detective found mysterious" in lines[0]

    def test_directed_message_gets_relevance_boost(self):
        mem = PersonaMemory()
        alice = _slot("alice", persona="programmer")
        msgs = [
            _msg(0, "bob", "Short", recipient="alice"),
            _msg(0, "charlie", "Some random unrelated content here"),
        ]
        result = mem.build_context(alice, msgs, 0)
        # Directed message should be ranked high (0.8 floor)
        assert "Short" in result

    def test_messages_limited_to_15(self):
        mem = PersonaMemory()
        alice = _slot("alice", persona="x")
        msgs = [
            _msg(i, "bob", f"Message {i} about detective mystery investigation") for i in range(20)
        ]
        result = mem.build_context(alice, msgs, 19)
        # Should only include top 15 by relevance, sorted by round
        lines = result.split("\n")
        assert len(lines) <= 15

    def test_content_truncated_to_200_chars(self):
        mem = PersonaMemory()
        alice = _slot("alice")
        long_content = "x" * 300
        msgs = [_msg(0, "bob", long_content)]
        result = mem.build_context(alice, msgs, 0)
        assert len(result.split(": ", 1)[1]) <= 200

    def test_messages_sorted_by_round_after_ranking(self):
        mem = PersonaMemory()
        alice = _slot("alice", persona="detective")
        msgs = [
            _msg(2, "bob", "detective clue evidence"),
            _msg(0, "charlie", "detective mystery investigation"),
            _msg(1, "dave", "detective suspect guilty"),
        ]
        result = mem.build_context(alice, msgs, 2)
        lines = result.split("\n")
        # After top-N selection, should be re-sorted by round
        rounds = []
        for line in lines:
            if "[Round " in line:
                round_num = int(line.split("[Round ")[1].split("]")[0])
                rounds.append(round_num)
        assert rounds == sorted(rounds)
