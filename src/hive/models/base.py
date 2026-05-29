"""Base provider class for all LLM providers."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any, ClassVar, TypeVar

import httpx
from pydantic import BaseModel

from hive.runtime.types import GenerateResult, Message, StreamEvent, StreamEventType

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}
NON_RETRYABLE_STATUS_CODES = {400, 401, 403}
MAX_RETRIES = 3
BASE_DELAY = 1.0


class Capability(StrEnum):
    """Optional features a provider may support.

    Use with ``BaseProvider.supports()`` to branch on what a provider can do
    rather than special-casing provider classes.
    """

    TOOLS = "tools"
    STRUCTURED_OUTPUT = "structured_output"
    STREAMING = "streaming"


class Availability(StrEnum):
    """Why a provider is or isn't usable -- richer than a bare ``available`` bool."""

    AVAILABLE = "available"
    NO_API_KEY = "no_api_key"
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"


class BaseProvider(ABC):
    """Abstract base class for all LLM providers.

    Subclasses must implement:
    - available (property)
    - generate_with_metadata()

    Subclasses may override ``generate_structured()`` (a prompt-based fallback is
    provided), ``generate_stream()`` (defaults to a single non-streaming chunk),
    ``CAPABILITIES``/``supports()`` to advertise optional features, and
    ``availability()`` to distinguish a missing API key from an unreachable endpoint.
    """

    #: Optional features this provider supports. Subclasses extend as features land.
    CAPABILITIES: ClassVar[frozenset[Capability]] = frozenset(
        {Capability.TOOLS, Capability.STRUCTURED_OUTPUT}
    )

    def __init__(self, model: str, api_key: str | None = None):
        self._model = model
        self._api_key = api_key

    @property
    def model(self) -> str:
        return self._model

    @property
    @abstractmethod
    def available(self) -> bool: ...

    def supports(self, capability: Capability) -> bool:
        """Whether this provider supports a given optional capability."""
        return capability in self.CAPABILITIES

    def availability(self) -> Availability:
        """Why the provider is or isn't usable.

        The default derives from the boolean ``available``; providers override
        this to distinguish a missing API key from an unreachable endpoint.
        """
        return Availability.AVAILABLE if self.available else Availability.UNKNOWN

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Message:
        """Generate a response. Delegates to generate_with_metadata()."""
        result = await self.generate_with_metadata(messages, tools, temperature, max_tokens)
        return result.message

    @abstractmethod
    async def generate_with_metadata(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> GenerateResult: ...

    async def generate_structured(
        self,
        messages: list[Message],
        output_type: type[Any],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Any:
        """Generate a response validated against a Pydantic model.

        The base implementation is provider-agnostic: it asks for JSON via the
        prompt and parses the reply (``generate_structured_fallback``), so every
        provider supports structured output out of the box. Providers with a
        native mode (Anthropic tool_use, OpenAI ``response_format``) override this.
        """
        from hive.runtime.structured import generate_structured_fallback

        return await generate_structured_fallback(
            self, messages, output_type, temperature, max_tokens
        )

    async def generate_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a generation as a sequence of ``StreamEvent``s.

        The base implementation does not truly stream: it calls
        ``generate_with_metadata()`` and emits the full text as one ``TEXT``
        event followed by a terminal ``DONE`` event. Providers that support
        token streaming override this and advertise ``Capability.STREAMING``.
        """
        result = await self.generate_with_metadata(messages, tools, temperature, max_tokens)
        if result.message.content:
            yield StreamEvent(type=StreamEventType.TEXT, text=result.message.content)
        yield StreamEvent(type=StreamEventType.DONE, result=result)

    async def _retry_with_backoff(
        self,
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
                is_timeout = "timeout" in type(e).__name__.lower() or isinstance(e, TimeoutError)
                is_connect = isinstance(e, (httpx.ConnectError, ConnectionError))

                status = getattr(e, "status_code", getattr(e, "status", 0))
                if status in NON_RETRYABLE_STATUS_CODES and not is_connect:
                    raise

                is_retryable = status in RETRYABLE_STATUS_CODES or is_timeout or is_connect

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

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model={self._model!r})"

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self._model})"
