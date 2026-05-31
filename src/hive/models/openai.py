"""OpenAI provider (also base for OpenAI-compatible APIs)."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from hive.config import get_env
from hive.models.base import Availability, BaseProvider, Capability
from hive.models.conversion import (
    messages_to_openai,
    openai_response_to_message,
    tools_to_openai,
)
from hive.models.registry import estimate_cost
from hive.runtime.structured import (
    StructuredGenerateResult,
    generate_structured_fallback,
    pydantic_to_response_format,
)
from hive.runtime.types import (
    GenerateResult,
    Message,
    StreamEvent,
    StreamEventType,
    ToolCall,
)

logger = logging.getLogger(__name__)

_TEXT_ONLY_NUDGE = (
    "You have no tools available. Reply to the user in plain text. Do not call any tools."
)


def _is_tool_use_failed(error: Exception) -> bool:
    """True when a provider rejected a tool call made on a no-tools request.

    Provider-agnostic: matches Groq's ``tool_use_failed`` error code (in the
    exception's ``code`` or ``body['error']['code']``) or a message indicating the
    model called a tool when none were offered. OpenAI tolerates this by coercing
    the call to text; stricter providers (Groq) return a 400 instead.
    """
    if getattr(error, "code", None) == "tool_use_failed":
        return True
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("code") == "tool_use_failed":
            return True
    msg = str(getattr(error, "message", "") or error).lower()
    return "model called a tool" in msg


class OpenAI(BaseProvider):
    """OpenAI provider with native function calling.

    Also serves as the base class for OpenAI-compatible APIs
    (Groq, Fireworks, Ollama, LM Studio).
    """

    CAPABILITIES = BaseProvider.CAPABILITIES | {Capability.STREAMING}

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

    def availability(self) -> Availability:
        # Local servers fail by being unreachable; remote APIs fail on a missing key.
        if self._is_local:
            return Availability.AVAILABLE if self.available else Availability.UNREACHABLE
        return Availability.AVAILABLE if self._has_key else Availability.NO_API_KEY

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
        api_messages = messages_to_openai(messages)
        t0 = time.time()

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools_to_openai(tools)

        try:
            response = await self._retry_with_backoff(
                self._client.chat.completions.create, **kwargs
            )
        except Exception as e:
            # Recover only the no-tools case this targets: a tool_use_failed on a request
            # that *did* offer tools (e.g. a malformed schema) is a real error, so re-raise.
            if tools or not _is_tool_use_failed(e):
                raise
            # The model called a tool on a no-tools request and the provider rejected it
            # (e.g. Groq's tool_use_failed 400). Any tools already ran, so recover the turn
            # with a bounded text-only retry instead of surfacing the error.
            return await self._recover_no_tools(messages, temperature, max_tokens, t0)
        duration_ms = int((time.time() - t0) * 1000)

        input_tokens = 0
        output_tokens = 0
        if response.usage:
            input_tokens = response.usage.prompt_tokens or 0
            output_tokens = response.usage.completion_tokens or 0

        cost = estimate_cost(self._model, input_tokens, output_tokens)

        return GenerateResult(
            message=openai_response_to_message(response),
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            duration_ms=duration_ms,
        )

    async def _recover_no_tools(
        self,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        t0: float,
    ) -> GenerateResult:
        """Retry a no-tools call once with an explicit text-only instruction.

        Used after a provider rejects a tool call made when no tools were offered.
        The tools already ran, so the turn must still complete: if the retry also
        fails, return a clean empty-text result rather than raising.
        """
        recovery_messages = messages_to_openai([*messages, Message.user(_TEXT_ONLY_NUDGE)])
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": recovery_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        try:
            response = await self._retry_with_backoff(
                self._client.chat.completions.create, **kwargs
            )
        except Exception:
            logger.warning(
                "No-tools recovery retry for model %s failed; returning empty text",
                self._model,
            )
            return GenerateResult(
                message=Message.assistant(""),
                model=self._model,
                duration_ms=int((time.time() - t0) * 1000),
            )

        input_tokens = 0
        output_tokens = 0
        if response.usage:
            input_tokens = response.usage.prompt_tokens or 0
            output_tokens = response.usage.completion_tokens or 0

        return GenerateResult(
            message=openai_response_to_message(response),
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=estimate_cost(self._model, input_tokens, output_tokens),
            duration_ms=int((time.time() - t0) * 1000),
        )

    async def generate_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        """Stream text deltas, accumulating tool-call fragments for the final message.

        Opens a single streaming request without the retry wrapper used by the
        non-streaming path, since partial output cannot be safely replayed.
        """
        api_messages = messages_to_openai(messages)
        t0 = time.time()

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools_to_openai(tools)

        # Track whether any text reached the caller: once it has, recovery would yield a
        # duplicate run of events, so we only recover when the failure happens before any
        # content streamed -- the realistic tool_use_failed case (the model chose a tool
        # over text). Anything after that, or with tools offered, re-raises.
        yielded_text = False
        try:
            stream = await self._client.chat.completions.create(**kwargs)
            async for event in self._consume_stream(stream, t0):
                if event.type == StreamEventType.TEXT:
                    yielded_text = True
                yield event
            return
        except Exception as e:
            if yielded_text or tools or not _is_tool_use_failed(e):
                raise

        # The model called a tool on a no-tools request and the provider rejected it before
        # any content streamed -- retry once with a text-only instruction; fall back to
        # clean empty text.
        recovery_kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages_to_openai([*messages, Message.user(_TEXT_ONLY_NUDGE)]),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        try:
            stream = await self._client.chat.completions.create(**recovery_kwargs)
            async for event in self._consume_stream(stream, t0):
                yield event
        except Exception:
            logger.warning(
                "No-tools recovery stream for model %s failed; returning empty text",
                self._model,
            )
            yield StreamEvent(
                type=StreamEventType.DONE,
                result=GenerateResult(
                    message=Message.assistant(""),
                    model=self._model,
                    duration_ms=int((time.time() - t0) * 1000),
                ),
            )

    async def _consume_stream(self, stream: Any, t0: float) -> AsyncIterator[StreamEvent]:
        """Emit TEXT deltas from a chat-completion stream, then a terminal DONE event.

        Accumulates tool-call fragments into the final message so callers see a
        complete ``GenerateResult`` on DONE.
        """
        content_parts: list[str] = []
        # tool-call index -> accumulated {id, name, args}
        tool_acc: dict[int, dict[str, str]] = {}
        input_tokens = 0
        output_tokens = 0

        async for chunk in stream:
            if chunk.usage:
                input_tokens = chunk.usage.prompt_tokens or 0
                output_tokens = chunk.usage.completion_tokens or 0
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                content_parts.append(delta.content)
                yield StreamEvent(type=StreamEventType.TEXT, text=delta.content)
            for tc in delta.tool_calls or []:
                slot = tool_acc.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function and tc.function.name:
                    slot["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    slot["args"] += tc.function.arguments

        tool_calls: list[ToolCall] = []
        for index in sorted(tool_acc):
            slot = tool_acc[index]
            try:
                args = json.loads(slot["args"]) if slot["args"] else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=slot["id"], name=slot["name"], arguments=args))

        content = "".join(content_parts)
        message = Message.assistant(content, tool_calls or None)
        duration_ms = int((time.time() - t0) * 1000)
        cost = estimate_cost(self._model, input_tokens, output_tokens)

        yield StreamEvent(
            type=StreamEventType.DONE,
            result=GenerateResult(
                message=message,
                model=self._model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
                duration_ms=duration_ms,
            ),
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

        api_messages = messages_to_openai(messages)
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

    def __repr__(self) -> str:
        base = f"{self.__class__.__name__}(model={self._model!r}"
        if self._base_url:
            base += f", base_url={self._base_url!r}"
        return base + ")"
