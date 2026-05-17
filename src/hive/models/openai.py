"""OpenAI provider (also base for OpenAI-compatible APIs)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from hive.config import get_env
from hive.models.base import BaseProvider
from hive.models.registry import estimate_cost
from hive.runtime.structured import (
    StructuredGenerateResult,
    generate_structured_fallback,
    pydantic_to_response_format,
)
from hive.runtime.types import GenerateResult, Message, Role, ToolCall

logger = logging.getLogger(__name__)


class OpenAI(BaseProvider):
    """OpenAI provider with native function calling.

    Also serves as the base class for OpenAI-compatible APIs
    (Groq, Fireworks, Ollama, LM Studio).
    """

    def __init__(
        self,
        model: str = "gpt-5.4-nano",
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        import openai

        key = api_key or get_env("OPENAI_API_KEY") or None
        super().__init__(model, key)

        client_kwargs: dict[str, Any] = {"api_key": key or "not-set"}
        if base_url:
            client_kwargs["base_url"] = base_url

        self._client = openai.AsyncOpenAI(**client_kwargs)
        self._has_key = bool(key)
        self._base_url = base_url
        self._is_local = base_url is not None and (
            "localhost" in base_url or "127.0.0.1" in base_url
        )
        self._health_cache: bool | None = None
        self._health_cache_time: float = 0.0

    # --- Tier presets ---

    @classmethod
    def lite(cls, **kwargs: Any) -> OpenAI:
        """GPT-5.4 Nano — fast and cheap."""
        return cls(model="gpt-5.4-nano", **kwargs)

    @classmethod
    def standard(cls, **kwargs: Any) -> OpenAI:
        """GPT-5.4 Mini — balanced."""
        return cls(model="gpt-5.4-mini", **kwargs)

    @classmethod
    def pro(cls, **kwargs: Any) -> OpenAI:
        """GPT-5.4 — most capable."""
        return cls(model="gpt-5.4", **kwargs)

    # --- Provider interface ---

    @property
    def available(self) -> bool:
        if self._is_local:
            now = time.time()
            if self._health_cache is not None and (now - self._health_cache_time) < 30:
                return self._health_cache
            result = self._check_local_health()
            self._health_cache = result
            self._health_cache_time = now
            return result
        return self._has_key

    def _check_local_health(self) -> bool:
        """Check if a local model server is reachable."""
        import concurrent.futures

        import httpx

        def _probe() -> bool:
            try:
                url = f"{self._base_url}/models" if self._base_url else ""
                resp = httpx.get(url, timeout=2.0)
                return resp.status_code == 200
            except Exception:
                return False

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(_probe).result(timeout=3.0)
        except Exception:
            return False

    async def generate_with_metadata(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> GenerateResult:
        api_messages = self._messages_to_openai(messages)
        t0 = time.time()

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = self._tools_to_openai(tools)

        response = await self._retry_with_backoff(self._client.chat.completions.create, **kwargs)
        duration_ms = int((time.time() - t0) * 1000)

        input_tokens = 0
        output_tokens = 0
        if response.usage:
            input_tokens = response.usage.prompt_tokens or 0
            output_tokens = response.usage.completion_tokens or 0

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
        if self._is_local:
            return await generate_structured_fallback(
                self, messages, output_type, temperature, max_tokens
            )

        api_messages = self._messages_to_openai(messages)
        t0 = time.time()

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "response_format": pydantic_to_response_format(output_type),
        }

        try:
            response = await self._retry_with_backoff(
                self._client.chat.completions.create, **kwargs
            )
        except Exception as e:
            if "response format" in str(e).lower() or "json_schema" in str(e).lower():
                logger.info(
                    "Model %s doesn't support json_schema, using fallback",
                    self._model,
                )
                return await generate_structured_fallback(
                    self, messages, output_type, temperature, max_tokens
                )
            raise

        duration_ms = int((time.time() - t0) * 1000)

        input_tokens = 0
        output_tokens = 0
        if response.usage:
            input_tokens = response.usage.prompt_tokens or 0
            output_tokens = response.usage.completion_tokens or 0

        cost = estimate_cost(self._model, input_tokens, output_tokens)
        content = response.choices[0].message.content or ""
        parsed = output_type.model_validate_json(content)

        gen_result = GenerateResult(
            message=Message.assistant(content),
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            duration_ms=duration_ms,
        )
        return StructuredGenerateResult(result=gen_result, parsed=parsed)

    # --- Internal helpers ---

    def _messages_to_openai(self, messages: list[Message]) -> list[dict[str, Any]]:
        api_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == Role.SYSTEM:
                api_messages.append({"role": "system", "content": msg.content})
            elif msg.role == Role.USER:
                api_messages.append({"role": "user", "content": msg.content})
            elif msg.role == Role.ASSISTANT:
                entry: dict[str, Any] = {"role": "assistant"}
                if msg.content:
                    entry["content"] = msg.content
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                if not msg.content and not msg.tool_calls:
                    entry["content"] = ""
                api_messages.append(entry)
            elif msg.role == Role.TOOL:
                api_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id,
                        "content": msg.content,
                    }
                )

        return api_messages

    def _tools_to_openai(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ]

    def _response_to_message(self, response: Any) -> Message:
        choice = response.choices[0]
        msg = choice.message
        content = msg.content or ""

        tool_calls: list[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        return Message.assistant(content, tool_calls or None)

    def __repr__(self) -> str:
        base = f"{self.__class__.__name__}(model={self._model!r}"
        if self._base_url:
            base += f", base_url={self._base_url!r}"
        return base + ")"
