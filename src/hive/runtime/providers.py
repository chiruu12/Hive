"""Runtime providers with native tool-use support."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Protocol, TypeVar, runtime_checkable

from hive.runtime.types import GenerateResult, Message, Role, ToolCall

logger = logging.getLogger(__name__)

R = TypeVar("R")

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}
MAX_RETRIES = 3
BASE_DELAY = 1.0


async def _retry_with_backoff(
    fn: Any,
    *args: Any,
    max_retries: int = MAX_RETRIES,
    base_delay: float = BASE_DELAY,
    **kwargs: Any,
) -> Any:
    """Call an async function with exponential backoff on transient errors."""
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            status = getattr(e, "status_code", getattr(e, "status", 0))
            is_timeout = "timeout" in type(e).__name__.lower() or isinstance(e, TimeoutError)
            is_retryable = status in RETRYABLE_STATUS_CODES or is_timeout

            if not is_retryable or attempt >= max_retries:
                raise

            delay = base_delay * (2**attempt)
            logger.warning(
                "Retryable error (attempt %d/%d, retry in %.1fs): %s",
                attempt + 1,
                max_retries + 1,
                delay,
                e,
            )
            last_error = e
            await asyncio.sleep(delay)

    raise last_error or RuntimeError("Retry exhausted")


@runtime_checkable
class RuntimeProvider(Protocol):
    """Provider protocol for the runtime. Returns Message with tool_calls."""

    @property
    def available(self) -> bool: ...

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Message: ...

    async def generate_with_metadata(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> GenerateResult: ...


class AnthropicRuntimeProvider:
    """Anthropic SDK with native tool_use support."""

    def __init__(self, model: str = "claude-haiku-4-5", api_key: str | None = None):
        import anthropic

        from hive.config import get_env

        key = api_key or get_env("ANTHROPIC_API_KEY") or None
        self._client = anthropic.AsyncAnthropic(api_key=key)
        self._model = model
        self._has_key = bool(key)

    @property
    def available(self) -> bool:
        return self._has_key

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Message:
        result = await self.generate_with_metadata(messages, tools, temperature, max_tokens)
        return result.message

    async def generate_with_metadata(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> GenerateResult:
        from hive.models.registry import estimate_cost

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

        response = await _retry_with_backoff(self._client.messages.create, **kwargs)
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

    async def generate_structured(
        self,
        messages: list[Message],
        output_type: type[Any],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Any:
        from hive.models.registry import estimate_cost
        from hive.runtime.structured import (
            StructuredGenerateResult,
            pydantic_to_json_schema,
        )

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

        response = await _retry_with_backoff(self._client.messages.create, **kwargs)
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


class OpenAIRuntimeProvider:
    """OpenAI SDK with native function calling. Works for OpenAI and Fireworks."""

    def __init__(
        self,
        model: str = "gpt-5.4-nano",
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        import openai

        from hive.config import get_env

        key = api_key or get_env("OPENAI_API_KEY") or None
        kwargs: dict[str, Any] = {}
        kwargs["api_key"] = key or "not-set"
        if base_url:
            kwargs["base_url"] = base_url
        self._client = openai.AsyncOpenAI(**kwargs)
        self._model = model
        self._has_key = bool(key)
        self._base_url = base_url
        self._is_local = base_url is not None and (
            "localhost" in base_url or "127.0.0.1" in base_url
        )
        self._health_cache: bool | None = None
        self._health_cache_time: float = 0.0

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
        """Check if a local model server is reachable (runs in thread to avoid blocking)."""
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

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Message:
        result = await self.generate_with_metadata(messages, tools, temperature, max_tokens)
        return result.message

    async def generate_with_metadata(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> GenerateResult:
        from hive.models.registry import estimate_cost

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

        response = await _retry_with_backoff(self._client.chat.completions.create, **kwargs)
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

    async def generate_structured(
        self,
        messages: list[Message],
        output_type: type[Any],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Any:
        from hive.models.registry import estimate_cost
        from hive.runtime.structured import (
            StructuredGenerateResult,
            generate_structured_fallback,
            pydantic_to_response_format,
        )

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
            response = await _retry_with_backoff(self._client.chat.completions.create, **kwargs)
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


def create_runtime_provider(model_name: str) -> RuntimeProvider:
    """Factory: route model name to the correct RuntimeProvider."""
    from hive.config import get_env

    if "claude" in model_name or model_name.startswith("claude-"):
        return AnthropicRuntimeProvider(model=model_name)

    if model_name.startswith("gpt-"):
        return OpenAIRuntimeProvider(model=model_name)

    if model_name.startswith(("fireworks:", "accounts/fireworks")):
        clean = model_name.removeprefix("fireworks:")
        key = get_env("FIREWORKS_API_KEY")
        return OpenAIRuntimeProvider(
            model=clean,
            api_key=key,
            base_url="https://api.fireworks.ai/inference/v1",
        )

    if model_name.startswith("groq:"):
        clean = model_name.removeprefix("groq:")
        key = get_env("GROQ_API_KEY")
        return OpenAIRuntimeProvider(
            model=clean,
            api_key=key,
            base_url="https://api.groq.com/openai/v1",
        )

    if model_name.startswith("lmstudio:"):
        clean = model_name.removeprefix("lmstudio:")
        return OpenAIRuntimeProvider(
            model=clean,
            api_key="lm-studio",
            base_url="http://localhost:1234/v1",
        )

    clean = model_name.removeprefix("ollama:")
    return OpenAIRuntimeProvider(
        model=clean,
        api_key="ollama",
        base_url="http://localhost:11434/v1",
    )
