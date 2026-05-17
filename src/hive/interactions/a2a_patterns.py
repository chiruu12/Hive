"""Higher-level A2A collaboration patterns."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from hive.interactions.a2a import A2AMessage, A2AMessageType, A2AStore


class A2APattern(ABC):
    """Base for structured multi-step A2A interaction patterns."""

    @abstractmethod
    async def execute(
        self,
        store: A2AStore,
        initiator: str,
        participants: list[str],
        context: str,
    ) -> dict[str, Any]: ...


class ReviewPattern(A2APattern):
    """Submit work -> review -> feedback -> optional revision (max 3 rounds)."""

    def __init__(self, max_rounds: int = 3):
        self.max_rounds = max_rounds

    async def execute(
        self,
        store: A2AStore,
        initiator: str,
        participants: list[str],
        context: str,
    ) -> dict[str, Any]:
        if not participants:
            return {"error": "No reviewer specified."}
        reviewer = participants[0]

        review_msg = A2AMessage(
            type=A2AMessageType.REVIEW,
            from_agent=initiator,
            to_agent=reviewer,
            subject="Review request",
            body=context,
            expects_reply=True,
        )
        await store.send(review_msg)

        return {
            "pattern": "review",
            "initiator": initiator,
            "reviewer": reviewer,
            "message_id": review_msg.message_id,
            "max_rounds": self.max_rounds,
            "status": "review_requested",
        }


class MentorPattern(A2APattern):
    """Senior agent guides junior through queries and guidance."""

    async def execute(
        self,
        store: A2AStore,
        initiator: str,
        participants: list[str],
        context: str,
    ) -> dict[str, Any]:
        if not participants:
            return {"error": "No mentor specified."}
        mentor = participants[0]

        query_msg = A2AMessage(
            type=A2AMessageType.QUERY,
            from_agent=initiator,
            to_agent=mentor,
            subject="Seeking guidance",
            body=context,
            expects_reply=True,
        )
        await store.send(query_msg)

        return {
            "pattern": "mentor",
            "mentee": initiator,
            "mentor": mentor,
            "message_id": query_msg.message_id,
            "status": "guidance_requested",
        }


class DebatePattern(A2APattern):
    """Two agents argue positions in structured rounds."""

    def __init__(self, rounds: int = 3):
        self.rounds = rounds

    async def execute(
        self,
        store: A2AStore,
        initiator: str,
        participants: list[str],
        context: str,
    ) -> dict[str, Any]:
        if not participants:
            return {"error": "No opponent specified."}
        opponent = participants[0]

        opening = A2AMessage(
            type=A2AMessageType.REQUEST,
            from_agent=initiator,
            to_agent=opponent,
            subject=f"Debate: {context[:60]}",
            body=f"Opening argument on: {context}",
            expects_reply=True,
            metadata={"debate_round": 1, "total_rounds": self.rounds},
        )
        await store.send(opening)

        return {
            "pattern": "debate",
            "side_a": initiator,
            "side_b": opponent,
            "topic": context,
            "message_id": opening.message_id,
            "rounds": self.rounds,
            "status": "opening_sent",
        }


class ChainPattern(A2APattern):
    """Sequential processing: A -> B -> C, each agent adds their part."""

    async def execute(
        self,
        store: A2AStore,
        initiator: str,
        participants: list[str],
        context: str,
    ) -> dict[str, Any]:
        if not participants:
            return {"error": "No chain participants specified."}

        first = participants[0]
        chain_msg = A2AMessage(
            type=A2AMessageType.DELEGATE,
            from_agent=initiator,
            to_agent=first,
            subject="Chain task",
            body=context,
            expects_reply=True,
            metadata={
                "chain": [initiator, *participants],
                "chain_index": 1,
            },
        )
        await store.send(chain_msg)

        return {
            "pattern": "chain",
            "initiator": initiator,
            "chain": [initiator, *participants],
            "message_id": chain_msg.message_id,
            "status": "chain_started",
        }


class SwarmTaskPattern(A2APattern):
    """Broadcast a task to all agents, collect responses."""

    async def execute(
        self,
        store: A2AStore,
        initiator: str,
        participants: list[str],
        context: str,
    ) -> dict[str, Any]:
        message_ids: list[str] = []
        for agent_id in participants:
            msg = A2AMessage(
                type=A2AMessageType.REQUEST,
                from_agent=initiator,
                to_agent=agent_id,
                subject="Swarm task",
                body=context,
                expects_reply=True,
                metadata={"swarm": True},
            )
            await store.send(msg)
            message_ids.append(msg.message_id)

        return {
            "pattern": "swarm",
            "initiator": initiator,
            "participants": participants,
            "message_ids": message_ids,
            "status": "broadcast_sent",
        }
