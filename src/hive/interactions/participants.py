"""Concrete Participant implementations for interactions."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from hive.interactions.base import InteractionMessage

logger = logging.getLogger(__name__)


class AgentParticipant:
    """Wraps a RuntimeProvider to participate in interactions."""

    def __init__(
        self,
        participant_id: str,
        name: str,
        model: Any,
        persona: str = "",
        system_prompt: str = "",
    ):
        self._id = participant_id
        self._name = name
        self._model = model
        self._persona = persona
        self._system_prompt = system_prompt

    @property
    def participant_id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    async def respond(
        self,
        messages: list[InteractionMessage],
        context: str = "",
        system_prompt: str = "",
    ) -> str:
        from hive.runtime.types import Message

        prompt = self._build_prompt(messages, context)
        sys_prompt = system_prompt or self._system_prompt

        msgs = []
        if sys_prompt:
            msgs.append(Message.system(sys_prompt))
        msgs.append(Message.user(prompt))

        response = await self._model.generate(
            messages=msgs,
            temperature=0.7,
            max_tokens=500,
        )
        return response.content.strip() if response.content else ""

    def _build_prompt(self, messages: list[InteractionMessage], context: str) -> str:
        lines: list[str] = []
        if self._persona:
            lines.append(f"You are {self._name}. {self._persona}")
        if context:
            lines.append(f"\nTopic: {context}")
        if messages:
            lines.append("\n--- Conversation so far ---")
            for m in messages:
                target = ""
                if m.recipient_id != "all":
                    target = f" → {m.recipient_id}"
                lines.append(f"[Round {m.round}] {m.sender_name}{target}: {m.content}")
        lines.append("\nRespond in character. Be concise (1-3 sentences).")
        return "\n".join(lines)


class HumanParticipant:
    """CLI-based human participant for interactive sessions."""

    def __init__(self, participant_id: str = "human", name: str = "Human"):
        self._id = participant_id
        self._name = name

    @property
    def participant_id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    async def respond(
        self,
        messages: list[InteractionMessage],
        context: str = "",
        system_prompt: str = "",
    ) -> str:
        for m in messages[-3:]:
            print(f"  [{m.sender_name}]: {m.content}")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: input(f"  {self._name}> "))


class EnvironmentParticipant:
    """Non-agent participant that returns programmatic responses.

    Useful for scenarios where the "environment" reveals information,
    presents challenges, or reacts to agent actions.
    """

    def __init__(
        self,
        participant_id: str = "environment",
        name: str = "Environment",
        response_fn: Callable[[list[InteractionMessage]], str | Awaitable[str]] | None = None,
    ):
        self._id = participant_id
        self._name = name
        self._response_fn = response_fn

    @property
    def participant_id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    async def respond(
        self,
        messages: list[InteractionMessage],
        context: str = "",
        system_prompt: str = "",
    ) -> str:
        if self._response_fn is None:
            return ""
        result = self._response_fn(messages)
        if asyncio.iscoroutine(result):
            return str(await result)
        return str(result)
