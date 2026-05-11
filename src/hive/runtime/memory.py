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
        """Drop oldest message groups, preserving tool_use/tool_result pairs."""
        if len(self._messages) <= self._max_messages:
            return

        groups = self._group_messages()

        first_user_group = None
        for i, group in enumerate(groups):
            if group[0].role == Role.USER:
                first_user_group = i
                break

        keep: list[Message] = []
        total = sum(len(g) for g in groups)
        dropped = 0
        target = total - self._max_messages

        for i, group in enumerate(groups):
            if i == first_user_group or dropped >= target:
                keep.extend(group)
            else:
                dropped += len(group)

        self._messages = keep

    def _group_messages(self) -> list[list[Message]]:
        """Group messages so assistant+tool_results stay together."""
        groups: list[list[Message]] = []
        i = 0
        while i < len(self._messages):
            msg = self._messages[i]
            if msg.role == Role.ASSISTANT and msg.tool_calls:
                group = [msg]
                i += 1
                while i < len(self._messages) and self._messages[i].role == Role.TOOL:
                    group.append(self._messages[i])
                    i += 1
                groups.append(group)
            else:
                groups.append([msg])
                i += 1
        return groups


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

            self._semantic = SemanticMemory(self._hive_dir, self._agent_name)
            return self._semantic
        except Exception:
            logger.debug("SemanticMemory unavailable, using in-memory fallback")
            return None

    def _memory_path(self) -> Path | None:
        if self._hive_dir is None:
            return None
        return self._hive_dir / "memory" / self._agent_name / "memories.jsonl"

    async def store(self, content: str, metadata: dict[str, Any] | None = None) -> str:
        """Store a memory entry."""
        semantic = self._get_semantic()
        if semantic:
            return str(await semantic.store(thought=content, metadata=metadata))

        import uuid

        mid = f"mem-{uuid.uuid4().hex[:8]}"
        self._fallback[mid] = {"thought": content, "metadata": metadata or {}}
        return mid

    async def recall(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Retrieve relevant memories by similarity."""
        semantic = self._get_semantic()
        if semantic:
            results = await semantic.search(query, top_k=limit)
            return [
                {"thought": r.thought, "metadata": r.metadata}
                for r in results
            ]

        entries = list(self._fallback.values())[-limit:]
        return entries

    async def clear(self) -> None:
        self._fallback.clear()
        self._semantic = None
        path = self._memory_path()
        if path and path.exists():
            path.unlink()
