"""Tests for A2A protocol — messaging, threading, toolkit, patterns."""

from pathlib import Path

import pytest

from hive.agents.state import AgentState, AgentStatus
from hive.interactions.a2a import REPLY_TYPE_MAP, A2AMessage, A2AMessageType, A2AStore
from hive.interactions.a2a_patterns import ReviewPattern, SwarmTaskPattern
from hive.memory.store import HiveStore
from hive.tools.a2a import A2AToolkit


@pytest.fixture
def a2a_store(tmp_path: Path) -> A2AStore:
    return A2AStore(tmp_path)


@pytest.fixture
async def hive_store(tmp_path: Path) -> HiveStore:
    s = HiveStore(tmp_path / "hive.db")
    await s.initialize()
    agent_a = AgentState(
        agent_id="agent-a", name="coder", role="Write code",
        model="test", status=AgentStatus.IDLE,
    )
    agent_b = AgentState(
        agent_id="agent-b", name="reviewer", role="Review code",
        model="test", status=AgentStatus.IDLE,
    )
    await s.save_agent(agent_a)
    await s.save_agent(agent_b)
    return s


class TestA2AStore:
    @pytest.mark.asyncio
    async def test_send_and_receive(self, a2a_store: A2AStore):
        msg = A2AMessage(
            type=A2AMessageType.REQUEST,
            from_agent="agent-a",
            to_agent="agent-b",
            subject="Help needed",
            body="Please review my code.",
            expects_reply=True,
        )
        await a2a_store.send(msg)

        inbox = await a2a_store.get_inbox("agent-b")
        assert len(inbox) == 1
        assert inbox[0].from_agent == "agent-a"
        assert inbox[0].subject == "Help needed"

        outbox = await a2a_store.get_outbox("agent-a")
        assert len(outbox) == 1

    @pytest.mark.asyncio
    async def test_unread_filter(self, a2a_store: A2AStore):
        msg = A2AMessage(
            type=A2AMessageType.QUERY,
            from_agent="agent-a",
            to_agent="agent-b",
            subject="Question",
            body="What do you think?",
        )
        await a2a_store.send(msg)

        inbox = await a2a_store.get_inbox("agent-b", unread_only=True)
        assert len(inbox) == 1

        await a2a_store.mark_read("agent-b", msg.message_id)

        inbox_after = await a2a_store.get_inbox("agent-b", unread_only=True)
        assert len(inbox_after) == 0

    @pytest.mark.asyncio
    async def test_thread_retrieval(self, a2a_store: A2AStore):
        msg1 = A2AMessage(
            type=A2AMessageType.REQUEST,
            from_agent="agent-a",
            to_agent="agent-b",
            subject="Review code",
            body="Please look at sort.py",
        )
        await a2a_store.send(msg1)

        msg2 = A2AMessage(
            type=A2AMessageType.RESPONSE,
            from_agent="agent-b",
            to_agent="agent-a",
            subject="Re: Review code",
            body="Looks good, minor issues.",
            reply_to=msg1.message_id,
        )
        await a2a_store.send(msg2)

        msg3 = A2AMessage(
            type=A2AMessageType.RESPONSE,
            from_agent="agent-a",
            to_agent="agent-b",
            subject="Re: Re: Review code",
            body="Fixed the issues.",
            reply_to=msg2.message_id,
        )
        await a2a_store.send(msg3)

        thread = await a2a_store.get_thread("agent-a", msg1.message_id)
        assert len(thread) == 3
        assert thread[0].message_id == msg1.message_id
        assert thread[-1].message_id == msg3.message_id

    @pytest.mark.asyncio
    async def test_get_message(self, a2a_store: A2AStore):
        msg = A2AMessage(
            type=A2AMessageType.QUERY,
            from_agent="agent-a",
            to_agent="agent-b",
            subject="Test",
            body="Hello",
        )
        await a2a_store.send(msg)

        found = await a2a_store.get_message("agent-b", msg.message_id)
        assert found is not None
        assert found.body == "Hello"

    @pytest.mark.asyncio
    async def test_pending_requests(self, a2a_store: A2AStore):
        msg = A2AMessage(
            type=A2AMessageType.REQUEST,
            from_agent="agent-a",
            to_agent="agent-b",
            subject="Do this",
            body="Task details",
            expects_reply=True,
        )
        await a2a_store.send(msg)

        pending = await a2a_store.get_pending_requests("agent-b")
        assert len(pending) == 1


class TestA2AToolkit:
    @pytest.mark.asyncio
    async def test_tool_discovery(
        self, a2a_store: A2AStore, hive_store: HiveStore
    ):
        tk = A2AToolkit(a2a_store, hive_store, agent_id="agent-a")
        tools = tk.get_tools()
        names = {t.name for t in tools}
        assert "send_request" in names
        assert "check_inbox" in names
        assert "reply" in names
        assert "reject_request" in names
        assert "find_agent" in names

    @pytest.mark.asyncio
    async def test_send_and_check_inbox(
        self, a2a_store: A2AStore, hive_store: HiveStore
    ):
        tk_a = A2AToolkit(a2a_store, hive_store, agent_id="agent-a")
        tk_b = A2AToolkit(a2a_store, hive_store, agent_id="agent-b")

        result = await tk_a.send_request(
            to_agent="agent-b",
            subject="Need review",
            body="Review sort.py please",
        )
        assert "sent" in result

        inbox = await tk_b.check_inbox(unread_only=True)
        assert "agent-a" in inbox
        assert "Need review" in inbox

    @pytest.mark.asyncio
    async def test_reply_auto_selects_type(
        self, a2a_store: A2AStore, hive_store: HiveStore
    ):
        msg = A2AMessage(
            type=A2AMessageType.QUERY,
            from_agent="agent-a",
            to_agent="agent-b",
            subject="Question",
            body="How does this work?",
        )
        await a2a_store.send(msg)

        tk_b = A2AToolkit(a2a_store, hive_store, agent_id="agent-b")
        result = await tk_b.reply(msg.message_id, "It works like this...")
        assert '"answer"' in result

    @pytest.mark.asyncio
    async def test_reject_request(
        self, a2a_store: A2AStore, hive_store: HiveStore
    ):
        msg = A2AMessage(
            type=A2AMessageType.REQUEST,
            from_agent="agent-a",
            to_agent="agent-b",
            subject="Big task",
            body="Do everything",
        )
        await a2a_store.send(msg)

        tk_b = A2AToolkit(a2a_store, hive_store, agent_id="agent-b")
        result = await tk_b.reject_request(msg.message_id, "Too busy")
        assert "rejected" in result

        inbox_a = await a2a_store.get_inbox("agent-a")
        reject_msgs = [m for m in inbox_a if m.type == A2AMessageType.REJECT]
        assert len(reject_msgs) == 1

    @pytest.mark.asyncio
    async def test_accept_request(
        self, a2a_store: A2AStore, hive_store: HiveStore
    ):
        msg = A2AMessage(
            type=A2AMessageType.DELEGATE,
            from_agent="agent-a",
            to_agent="agent-b",
            subject="Take this task",
            body="Review the PR",
        )
        await a2a_store.send(msg)

        tk_b = A2AToolkit(a2a_store, hive_store, agent_id="agent-b")
        result = await tk_b.accept_request(msg.message_id, "On it!")
        assert "accepted" in result

    @pytest.mark.asyncio
    async def test_list_agents(
        self, a2a_store: A2AStore, hive_store: HiveStore
    ):
        tk_a = A2AToolkit(a2a_store, hive_store, agent_id="agent-a")
        result = await tk_a.list_agents()
        assert "agent-b" in result
        assert "reviewer" in result


class TestA2APatterns:
    @pytest.mark.asyncio
    async def test_review_pattern(self, a2a_store: A2AStore):
        pattern = ReviewPattern(max_rounds=3)
        result = await pattern.execute(
            a2a_store, "agent-a", ["agent-b"], "Review my sort implementation"
        )
        assert result["status"] == "review_requested"
        assert result["reviewer"] == "agent-b"

        inbox = await a2a_store.get_inbox("agent-b")
        assert len(inbox) == 1
        assert inbox[0].type == A2AMessageType.REVIEW

    @pytest.mark.asyncio
    async def test_swarm_pattern(self, a2a_store: A2AStore):
        pattern = SwarmTaskPattern()
        result = await pattern.execute(
            a2a_store,
            "agent-a",
            ["agent-b", "agent-c"],
            "Solve this problem",
        )
        assert result["status"] == "broadcast_sent"
        assert len(result["message_ids"]) == 2

        inbox_b = await a2a_store.get_inbox("agent-b")
        inbox_c = await a2a_store.get_inbox("agent-c")
        assert len(inbox_b) == 1
        assert len(inbox_c) == 1


class TestReplyTypeMap:
    def test_request_maps_to_response(self):
        assert REPLY_TYPE_MAP[A2AMessageType.REQUEST] == A2AMessageType.RESPONSE

    def test_query_maps_to_answer(self):
        assert REPLY_TYPE_MAP[A2AMessageType.QUERY] == A2AMessageType.ANSWER

    def test_review_maps_to_feedback(self):
        assert REPLY_TYPE_MAP[A2AMessageType.REVIEW] == A2AMessageType.FEEDBACK

    def test_delegate_maps_to_ack(self):
        assert REPLY_TYPE_MAP[A2AMessageType.DELEGATE] == A2AMessageType.ACK
