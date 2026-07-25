"""Persist and restore ReAct conversation state for multi-heartbeat goal pursuit."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from hive.runtime.memory import ConversationMemory
from hive.runtime.types import Message, Role, ToolCall

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from hive.memory.store import HiveStore


def message_to_dict(msg: Message) -> dict[str, Any]:
    """Serialize a runtime Message to a JSON-safe dict."""
    data: dict[str, Any] = {"role": msg.role.value, "content": msg.content}
    if msg.tool_calls:
        data["tool_calls"] = [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in msg.tool_calls
        ]
    if msg.tool_call_id:
        data["tool_call_id"] = msg.tool_call_id
    if msg.name:
        data["name"] = msg.name
    if msg.is_error:
        data["is_error"] = True
    return data


def message_from_dict(data: dict[str, Any]) -> Message:
    """Deserialize a runtime Message from a JSON dict."""
    role = Role(data["role"])
    tool_calls: tuple[ToolCall, ...] = ()
    if raw_calls := data.get("tool_calls"):
        tool_calls = tuple(
            ToolCall(id=tc["id"], name=tc["name"], arguments=tc.get("arguments") or {})
            for tc in raw_calls
        )
    return Message(
        role=role,
        content=data.get("content", ""),
        tool_calls=tool_calls,
        tool_call_id=data.get("tool_call_id", ""),
        name=data.get("name", ""),
        is_error=bool(data.get("is_error", False)),
    )


def messages_match(a: list[Message], b: list[Message]) -> bool:
    """Return True when two message lists serialize identically."""
    if len(a) != len(b):
        return False
    return all(
        message_to_dict(left) == message_to_dict(right) for left, right in zip(a, b, strict=True)
    )


def truncate_messages(messages: list[Message], max_messages: int) -> list[Message]:
    """Cap transcript length, preserving assistant/tool groups like ConversationMemory."""
    if max_messages <= 0 or len(messages) <= max_messages:
        return messages
    memory = ConversationMemory(max_messages=max_messages)
    for msg in messages:
        memory.add(msg)
    return memory.messages


def parse_transcript_row(row: str, *, goal_id: str, agent_id: str, seq: int) -> Message | None:
    """Parse one stored row; return None and log on poison data."""
    try:
        data = json.loads(row)
        if not isinstance(data, dict):
            raise TypeError(f"expected object, got {type(data).__name__}")
        return message_from_dict(data)
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        logger.warning(
            "Skipping poison pursuit transcript row goal_id=%s agent_id=%s seq=%s: %s",
            goal_id,
            agent_id,
            seq,
            exc,
        )
        return None


class PursuitTranscriptStore:
    """Store-backed transcript archive keyed by goal_id."""

    def __init__(self, store: HiveStore, *, max_messages: int = 200) -> None:
        self._store = store
        self._max_messages = max_messages

    @property
    def max_messages(self) -> int:
        """Configured cap applied when persisting transcripts."""
        return self._max_messages

    async def load_messages(
        self,
        goal_id: str,
        agent_id: str,
        limit: int | None = None,
    ) -> list[Message]:
        """Load persisted pursuit messages for a goal, oldest first."""
        rows = await self._store.load_pursuit_messages(goal_id, agent_id, limit=limit)
        messages: list[Message] = []
        for seq, row in enumerate(rows):
            msg = parse_transcript_row(row, goal_id=goal_id, agent_id=agent_id, seq=seq)
            if msg is not None:
                messages.append(msg)
        return messages

    async def save_messages(
        self,
        goal_id: str,
        agent_id: str,
        messages: list[Message],
    ) -> None:
        """Replace the transcript for a goal with the full message list."""
        capped = truncate_messages(messages, self._max_messages)
        payload = [json.dumps(message_to_dict(msg)) for msg in capped]
        await self._store.save_pursuit_messages(goal_id, agent_id, payload)

    async def append_messages(
        self,
        goal_id: str,
        agent_id: str,
        messages: list[Message],
    ) -> None:
        """Append new messages to an existing transcript."""
        if not messages:
            return
        existing = await self.load_messages(goal_id, agent_id)
        await self.save_messages(goal_id, agent_id, [*existing, *messages])

    async def delete_transcript(self, goal_id: str) -> None:
        """Remove all persisted messages for a goal."""
        await self._store.delete_pursuit_transcript(goal_id)
