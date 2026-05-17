"""A2A Toolkit — agent-facing tools for structured messaging."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from hive.interactions.a2a import (
    REPLY_TYPE_MAP,
    A2AMessage,
    A2AMessageType,
    A2AStore,
)
from hive.memory.store import HiveStore
from hive.tools.base import Toolkit, tool

if TYPE_CHECKING:
    from hive.agents.specialization import SpecializationTracker


class A2AToolkit(Toolkit):
    """Agent-facing tools for the A2A protocol."""

    def __init__(
        self,
        a2a_store: A2AStore,
        hive_store: HiveStore,
        agent_id: str = "",
        specialization: SpecializationTracker | None = None,
    ):
        self._a2a = a2a_store
        self._agent_id = agent_id
        self._store = hive_store
        self._spec = specialization

    @tool()
    async def send_request(self, to_agent: str, subject: str, body: str, priority: int = 4) -> str:
        """Send a request to another agent expecting a response."""
        msg = A2AMessage(
            type=A2AMessageType.REQUEST,
            from_agent=self._agent_id,
            to_agent=to_agent,
            subject=subject,
            body=body,
            priority=priority,
            expects_reply=True,
        )
        await self._a2a.send(msg)
        return json.dumps(
            {
                "message_id": msg.message_id,
                "status": "sent",
                "to": to_agent,
            }
        )

    @tool()
    async def send_query(self, to_agent: str, question: str) -> str:
        """Ask another agent a question."""
        msg = A2AMessage(
            type=A2AMessageType.QUERY,
            from_agent=self._agent_id,
            to_agent=to_agent,
            subject=question[:80],
            body=question,
            expects_reply=True,
        )
        await self._a2a.send(msg)
        return json.dumps(
            {
                "message_id": msg.message_id,
                "status": "sent",
                "to": to_agent,
            }
        )

    @tool()
    async def send_review_request(self, to_agent: str, subject: str, body: str) -> str:
        """Request a peer review from another agent."""
        msg = A2AMessage(
            type=A2AMessageType.REVIEW,
            from_agent=self._agent_id,
            to_agent=to_agent,
            subject=subject,
            body=body,
            expects_reply=True,
        )
        await self._a2a.send(msg)
        return json.dumps(
            {
                "message_id": msg.message_id,
                "status": "sent",
                "to": to_agent,
            }
        )

    @tool()
    async def check_inbox(self, unread_only: bool = True) -> str:
        """Check your inbox for messages."""
        messages = await self._a2a.get_inbox(self._agent_id, unread_only=unread_only, limit=10)
        if not messages:
            return "No messages." if unread_only else "Inbox is empty."
        lines = []
        for m in messages:
            unread = " [UNREAD]" if not m.read else ""
            lines.append(
                f"- {m.message_id}: [{m.type}] from={m.from_agent} "
                f'subject="{m.subject[:50]}"{unread}'
            )
        return "\n".join(lines)

    @tool()
    async def read_message(self, message_id: str) -> str:
        """Read a specific message in detail."""
        msg = await self._a2a.get_message(self._agent_id, message_id)
        if not msg:
            return f"Message {message_id} not found."
        await self._a2a.mark_read(self._agent_id, message_id)
        return json.dumps(
            {
                "message_id": msg.message_id,
                "type": msg.type,
                "from": msg.from_agent,
                "to": msg.to_agent,
                "subject": msg.subject,
                "body": msg.body,
                "reply_to": msg.reply_to,
                "priority": msg.priority,
                "expects_reply": msg.expects_reply,
                "ts": msg.ts.isoformat(),
            }
        )

    @tool()
    async def reply(self, message_id: str, body: str) -> str:
        """Reply to a message. Auto-selects the correct response type."""
        original = await self._a2a.get_message(self._agent_id, message_id)
        if not original:
            return f"Message {message_id} not found."
        reply_type = REPLY_TYPE_MAP.get(original.type, A2AMessageType.RESPONSE)
        msg = A2AMessage(
            type=reply_type,
            from_agent=self._agent_id,
            to_agent=original.from_agent,
            subject=f"Re: {original.subject[:70]}",
            body=body,
            reply_to=message_id,
        )
        await self._a2a.send(msg)
        return json.dumps(
            {
                "message_id": msg.message_id,
                "type": reply_type,
                "status": "sent",
            }
        )

    @tool()
    async def accept_request(self, message_id: str, body: str = "") -> str:
        """Accept a request or delegation with an ACK."""
        original = await self._a2a.get_message(self._agent_id, message_id)
        if not original:
            return f"Message {message_id} not found."
        msg = A2AMessage(
            type=A2AMessageType.ACK,
            from_agent=self._agent_id,
            to_agent=original.from_agent,
            subject=f"ACK: {original.subject[:70]}",
            body=body or "Accepted.",
            reply_to=message_id,
        )
        await self._a2a.send(msg)
        return json.dumps(
            {
                "message_id": msg.message_id,
                "status": "accepted",
            }
        )

    @tool()
    async def reject_request(self, message_id: str, reason: str = "") -> str:
        """Reject a request or delegation with a reason."""
        original = await self._a2a.get_message(self._agent_id, message_id)
        if not original:
            return f"Message {message_id} not found."
        msg = A2AMessage(
            type=A2AMessageType.REJECT,
            from_agent=self._agent_id,
            to_agent=original.from_agent,
            subject=f"Rejected: {original.subject[:65]}",
            body=reason or "Unable to fulfill this request.",
            reply_to=message_id,
        )
        await self._a2a.send(msg)
        return json.dumps(
            {
                "message_id": msg.message_id,
                "status": "rejected",
            }
        )

    @tool()
    async def list_agents(self) -> str:
        """List all available agents you can message."""
        agents = await self._store.list_agents()
        alive = [a for a in agents if a.is_alive() and a.agent_id != self._agent_id]
        if not alive:
            return "No other agents available."
        lines = []
        for a in alive:
            tag = " [sub]" if a.spawned_by else ""
            lines.append(f"- {a.agent_id}: {a.name} ({a.role}){tag}")
        return "\n".join(lines)

    @tool()
    async def find_agent(self, capability: str) -> str:
        """Find the best agent for a given capability/task type."""
        if not self._spec:
            result: str = await self.list_agents()
            return result
        agents = await self._store.list_agents()
        alive = [a.agent_id for a in agents if a.is_alive() and a.agent_id != self._agent_id]
        best = self._spec.best_agent_for(capability, alive)
        if best:
            agent = await self._store.get_agent(best)
            name = agent.name if agent else best
            return f"Best agent for '{capability}': {best} ({name})"
        return f"No specialized agent found for '{capability}'."
