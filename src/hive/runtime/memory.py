"""Conversation and persistent memory for the agent runtime."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from hive.runtime.types import Message, Role

logger = logging.getLogger(__name__)


class ConversationMemory:
    """In-memory message buffer for a single agent task."""

    def __init__(self, system_prompt: str = "", max_messages: int = 100):
        self._system_prompt = system_prompt
        self._max_messages = max_messages
        self._messages: list[Message] = []

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str) -> None:
        self._system_prompt = value

    def add(self, message: Message) -> None:
        self._messages.append(message)
        if len(self._messages) > self._max_messages:
            self._truncate()

    def get_messages(self) -> list[Message]:
        msgs: list[Message] = []
        if self._system_prompt:
            msgs.append(Message.system(self._system_prompt))
        msgs.extend(self._messages)
        return msgs

    def clear(self) -> None:
        self._messages.clear()

    def _truncate(self) -> None:
        """Drop oldest non-system messages, preserving the first user message."""
        if len(self._messages) <= self._max_messages:
            return

        first_user_idx = None
        for i, msg in enumerate(self._messages):
            if msg.role == Role.USER:
                first_user_idx = i
                break

        drop_count = len(self._messages) - self._max_messages
        keep: list[Message] = []
        dropped = 0

        for i, msg in enumerate(self._messages):
            if i == first_user_idx or dropped >= drop_count:
                keep.append(msg)
            else:
                dropped += 1

        self._messages = keep


class PersistentMemory:
    """Cross-session memory wrapping SemanticMemory."""

    def __init__(self, agent_name: str, hive_dir: Path | None = None):
        self._agent_name = agent_name
        self._hive_dir = hive_dir
        self._semantic: Any = None
        self._fallback: dict[str, dict[str, Any]] = {}

    def _get_semantic(self) -> Any:
        if self._semantic is not None:
            return self._semantic

        if self._hive_dir is None:
            return None

        try:
            from hive.memory.semantic import SemanticMemory

            self._semantic = SemanticMemory(self._agent_name, self._hive_dir)
            return self._semantic
        except Exception:
            logger.debug("SemanticMemory unavailable, using in-memory fallback")
            return None

    async def store(self, content: str, metadata: dict[str, Any] | None = None) -> str:
        """Store a memory entry."""
        semantic = self._get_semantic()
        if semantic:
            await semantic.add_observation(content, importance=0.5)
            return f"mem-{self._agent_name}-{len(self._fallback)}"

        import uuid

        mid = f"mem-{uuid.uuid4().hex[:8]}"
        self._fallback[mid] = {"thought": content, "metadata": metadata or {}}
        return mid

    async def recall(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Retrieve relevant memories by similarity."""
        semantic = self._get_semantic()
        if semantic:
            results = await semantic.query(query, top_k=limit)
            return results

        entries = list(self._fallback.values())[-limit:]
        return entries

    async def clear(self) -> None:
        self._fallback.clear()
        self._semantic = None
