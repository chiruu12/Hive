"""Agent-to-Agent interaction protocol — structured typed messaging."""

import json
import logging
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class A2AMessageType(StrEnum):
    REQUEST = "request"
    RESPONSE = "response"
    QUERY = "query"
    ANSWER = "answer"
    REVIEW = "review"
    FEEDBACK = "feedback"
    DELEGATE = "delegate"
    ACK = "ack"
    REJECT = "reject"


REPLY_TYPE_MAP: dict[A2AMessageType, A2AMessageType] = {
    A2AMessageType.REQUEST: A2AMessageType.RESPONSE,
    A2AMessageType.QUERY: A2AMessageType.ANSWER,
    A2AMessageType.REVIEW: A2AMessageType.FEEDBACK,
    A2AMessageType.DELEGATE: A2AMessageType.ACK,
}


class A2AMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: f"msg-{uuid4().hex[:8]}")
    type: A2AMessageType
    from_agent: str
    to_agent: str
    subject: str
    body: str
    reply_to: str | None = None
    priority: int = 4
    expects_reply: bool = False
    read: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))


class A2AStore:
    """JSONL file-based message storage per agent."""

    def __init__(self, hive_dir: Path):
        self._a2a_dir = hive_dir / "a2a"
        self._a2a_dir.mkdir(parents=True, exist_ok=True)

    def _inbox_path(self, agent_id: str) -> Path:
        d = self._a2a_dir / agent_id
        d.mkdir(parents=True, exist_ok=True)
        return d / "inbox.jsonl"

    def _outbox_path(self, agent_id: str) -> Path:
        d = self._a2a_dir / agent_id
        d.mkdir(parents=True, exist_ok=True)
        return d / "outbox.jsonl"

    async def send(self, message: A2AMessage) -> None:
        """Write to sender's outbox AND recipient's inbox."""
        line = message.model_dump_json() + "\n"
        outbox = self._outbox_path(message.from_agent)
        inbox = self._inbox_path(message.to_agent)
        with open(outbox, "a") as f:
            f.write(line)
        with open(inbox, "a") as f:
            f.write(line)

    async def get_inbox(
        self,
        agent_id: str,
        unread_only: bool = False,
        limit: int = 20,
    ) -> list[A2AMessage]:
        path = self._inbox_path(agent_id)
        if not path.exists():
            return []
        messages: list[A2AMessage] = []
        for line in path.read_text().strip().splitlines():
            if not line.strip():
                continue
            try:
                msg = A2AMessage.model_validate_json(line)
                if unread_only and msg.read:
                    continue
                messages.append(msg)
            except Exception:
                continue
        messages.sort(key=lambda m: m.ts, reverse=True)
        return messages[:limit]

    async def get_outbox(self, agent_id: str, limit: int = 20) -> list[A2AMessage]:
        path = self._outbox_path(agent_id)
        if not path.exists():
            return []
        messages: list[A2AMessage] = []
        for line in path.read_text().strip().splitlines():
            if not line.strip():
                continue
            try:
                messages.append(A2AMessage.model_validate_json(line))
            except Exception:
                continue
        messages.sort(key=lambda m: m.ts, reverse=True)
        return messages[:limit]

    async def get_message(self, agent_id: str, message_id: str) -> A2AMessage | None:
        for path in [self._inbox_path(agent_id), self._outbox_path(agent_id)]:
            if not path.exists():
                continue
            for line in path.read_text().strip().splitlines():
                if message_id in line:
                    try:
                        msg = A2AMessage.model_validate_json(line)
                        if msg.message_id == message_id:
                            return msg
                    except Exception:
                        continue
        return None

    async def get_thread(self, agent_id: str, root_message_id: str) -> list[A2AMessage]:
        all_msgs = await self.get_inbox(agent_id, limit=100)
        all_msgs.extend(await self.get_outbox(agent_id, limit=100))

        seen: set[str] = set()
        unique: list[A2AMessage] = []
        for m in all_msgs:
            if m.message_id not in seen:
                seen.add(m.message_id)
                unique.append(m)

        thread_ids = {root_message_id}
        changed = True
        while changed:
            changed = False
            for m in unique:
                if m.message_id in thread_ids:
                    continue
                if m.reply_to in thread_ids:
                    thread_ids.add(m.message_id)
                    changed = True

        result = [m for m in unique if m.message_id in thread_ids]
        result.sort(key=lambda m: m.ts)
        return result

    async def mark_read(self, agent_id: str, message_id: str) -> None:
        path = self._inbox_path(agent_id)
        if not path.exists():
            return
        lines = path.read_text().strip().splitlines()
        updated: list[str] = []
        for line in lines:
            if message_id in line:
                try:
                    data = json.loads(line)
                    data["read"] = True
                    updated.append(json.dumps(data, default=str))
                    continue
                except Exception:
                    pass
            updated.append(line)
        path.write_text("\n".join(updated) + "\n" if updated else "")

    async def get_pending_requests(self, agent_id: str, limit: int = 5) -> list[A2AMessage]:
        inbox = await self.get_inbox(agent_id, unread_only=True, limit=limit)
        return [m for m in inbox if m.expects_reply]
