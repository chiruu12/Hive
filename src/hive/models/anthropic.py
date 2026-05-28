"""Anthropic Claude provider."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from hive.config import get_env
from hive.models.base import Availability, BaseProvider
from hive.models.registry import estimate_cost
from hive.runtime.structured import StructuredGenerateResult, pydantic_to_json_schema
from hive.runtime.types import GenerateResult, Message, Role, ToolCall

logger = logging.getLogger(__name__)


class Anthropic(BaseProvider):
    """Anthropic Claude provider with native tool_use support."""

    def __init__(self, model: str = "claude-sonnet-4-6", api_key: str | None = None):
        import anthropic

        key = api_key or get_env("ANTHROPIC_API_KEY") or None
        super().__init__(model, key)
        self._client = anthropic.AsyncAnthropic(api_key=key)
        self._has_key = bool(key)

    # --- Tier presets ---

    @classmethod
    def lite(cls, **kwargs: Any) -> Anthropic:
        """Claude Haiku — fast and cheap."""
        return cls(model="claude-haiku-4-5", **kwargs)

    @classmethod
    def standard(cls, **kwargs: Any) -> Anthropic:
        """Claude Sonnet — balanced."""
        return cls(model="claude-sonnet-4-6", **kwargs)

    @classmethod
    def pro(cls, **kwargs: Any) -> Anthropic:
        """Claude Opus — most capable."""
        return cls(model="claude-opus-4-6", **kwargs)

    # --- Provider interface ---

    @property
    def available(self) -> bool:
        return self._has_key

    def availability(self) -> Availability:
        return Availability.AVAILABLE if self._has_key else Availability.NO_API_KEY

    async def generate_with_metadata(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> GenerateResult:
        system, api_messages = self._messages_to_anthropic(messages)
        t0 = time.time()

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": t["input_schema"],
                }
                for t in tools
            ]

        response = await self._retry_with_backoff(self._client.messages.create, **kwargs)
        duration_ms = int((time.time() - t0) * 1000)

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = estimate_cost(self._model, input_tokens, output_tokens)

        return GenerateResult(
            message=self._response_to_message(response),
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            duration_ms=duration_ms,
        )

    async def generate_structured(
        self,
        messages: list[Message],
        output_type: type[Any],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Any:
        schema = pydantic_to_json_schema(output_type)
        system, api_messages = self._messages_to_anthropic(messages)
        t0 = time.time()

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "tools": [
                {
                    "name": "structured_output",
                    "description": f"Return a {output_type.__name__} response",
                    "input_schema": schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": "structured_output"},
        }
        if system:
            kwargs["system"] = system

        response = await self._retry_with_backoff(self._client.messages.create, **kwargs)
        duration_ms = int((time.time() - t0) * 1000)

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = estimate_cost(self._model, input_tokens, output_tokens)

        tool_input: dict[str, Any] = {}
        for block in response.content:
            if block.type == "tool_use":
                tool_input = block.input
                break

        parsed = output_type.model_validate(tool_input)

        gen_result = GenerateResult(
            message=Message.assistant(json.dumps(tool_input)),
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            duration_ms=duration_ms,
        )
        return StructuredGenerateResult(result=gen_result, parsed=parsed)

    # --- Internal helpers ---

    def _messages_to_anthropic(self, messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
        system = ""
        api_messages: list[dict[str, Any]] = []
        pending_tool_results: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == Role.SYSTEM:
                system = (system + "\n" + msg.content).strip()
                continue

            if msg.role == Role.USER:
                if pending_tool_results:
                    api_messages.append({"role": "user", "content": pending_tool_results})
                    pending_tool_results = []
                api_messages.append({"role": "user", "content": msg.content})

            elif msg.role == Role.ASSISTANT:
                if pending_tool_results:
                    api_messages.append({"role": "user", "content": pending_tool_results})
                    pending_tool_results = []

                content: list[dict[str, Any]] = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        }
                    )
                api_messages.append({"role": "assistant", "content": content or msg.content})

            elif msg.role == Role.TOOL:
                tool_result: dict[str, Any] = {
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id,
                    "content": msg.content,
                }
                if msg.is_error:
                    tool_result["is_error"] = True
                pending_tool_results.append(tool_result)

        if pending_tool_results:
            api_messages.append({"role": "user", "content": pending_tool_results})

        return system, api_messages

    def _response_to_message(self, response: Any) -> Message:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input,
                    )
                )

        return Message.assistant("\n".join(text_parts), tool_calls or None)
