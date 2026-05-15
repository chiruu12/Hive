"""Base provider class for all LLM providers."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel

from hive.runtime.types import GenerateResult, Message

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}
MAX_RETRIES = 3
BASE_DELAY = 1.0


class BaseProvider(ABC):
    """Abstract base class for all LLM providers.

    Subclasses must implement:
    - available (property)
    - generate_with_metadata()
    - generate_structured()
    """

    def __init__(self, model: str, api_key: str | None = None):
        self._model = model
        self._api_key = api_key

    @property
    def model(self) -> str:
        return self._model

    @property
    @abstractmethod
    def available(self) -> bool: ...

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

    @abstractmethod
    async def generate_structured(
        self,
        messages: list[Message],
        output_type: type[Any],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Any: ...

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

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model={self._model!r})"

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self._model})"
