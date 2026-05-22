"""Tests for BaseProvider._retry_with_backoff() retry logic."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from hive.models.base import BaseProvider
from hive.runtime.types import GenerateResult, Message


class _StubProvider(BaseProvider):
    """Minimal concrete provider for testing retry logic."""

    @property
    def available(self) -> bool:
        return True

    async def generate_with_metadata(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> GenerateResult:
        return await self._retry_with_backoff(self._inner_call, messages, tools)

    async def generate_structured(
        self,
        messages: list[Message],
        output_type: type[Any],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Any:
        return None

    async def _inner_call(self, messages: Any, tools: Any) -> GenerateResult:
        raise NotImplementedError


class _APIError(Exception):
    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"API error {status_code}")


@pytest.fixture
def provider() -> _StubProvider:
    return _StubProvider(model="test-model")


@pytest.mark.asyncio
@patch("asyncio.sleep", new_callable=AsyncMock)
async def test_429_retries_then_succeeds(mock_sleep: AsyncMock, provider: _StubProvider) -> None:
    fn = AsyncMock(side_effect=[_APIError(429), _APIError(429), "ok"])
    result = await provider._retry_with_backoff(fn)
    assert result == "ok"
    assert fn.call_count == 3
    assert mock_sleep.call_count == 2


@pytest.mark.asyncio
@patch("asyncio.sleep", new_callable=AsyncMock)
async def test_500_retries(mock_sleep: AsyncMock, provider: _StubProvider) -> None:
    fn = AsyncMock(side_effect=[_APIError(500), "ok"])
    result = await provider._retry_with_backoff(fn)
    assert result == "ok"
    assert fn.call_count == 2


@pytest.mark.asyncio
@patch("asyncio.sleep", new_callable=AsyncMock)
async def test_502_503_529_retry(mock_sleep: AsyncMock, provider: _StubProvider) -> None:
    for code in (502, 503, 529):
        fn = AsyncMock(side_effect=[_APIError(code), "ok"])
        result = await provider._retry_with_backoff(fn)
        assert result == "ok"


@pytest.mark.asyncio
@patch("asyncio.sleep", new_callable=AsyncMock)
async def test_connect_error_retries(mock_sleep: AsyncMock, provider: _StubProvider) -> None:
    fn = AsyncMock(side_effect=[httpx.ConnectError("refused"), "ok"])
    result = await provider._retry_with_backoff(fn)
    assert result == "ok"
    assert fn.call_count == 2


@pytest.mark.asyncio
@patch("asyncio.sleep", new_callable=AsyncMock)
async def test_connection_error_retries(mock_sleep: AsyncMock, provider: _StubProvider) -> None:
    fn = AsyncMock(side_effect=[ConnectionError("reset"), "ok"])
    result = await provider._retry_with_backoff(fn)
    assert result == "ok"
    assert fn.call_count == 2


@pytest.mark.asyncio
@patch("asyncio.sleep", new_callable=AsyncMock)
async def test_timeout_error_retries(mock_sleep: AsyncMock, provider: _StubProvider) -> None:
    fn = AsyncMock(side_effect=[TimeoutError("timed out"), "ok"])
    result = await provider._retry_with_backoff(fn)
    assert result == "ok"
    assert fn.call_count == 2


@pytest.mark.asyncio
async def test_401_does_not_retry(provider: _StubProvider) -> None:
    fn = AsyncMock(side_effect=_APIError(401))
    with pytest.raises(_APIError, match="401"):
        await provider._retry_with_backoff(fn)
    assert fn.call_count == 1


@pytest.mark.asyncio
async def test_403_does_not_retry(provider: _StubProvider) -> None:
    fn = AsyncMock(side_effect=_APIError(403))
    with pytest.raises(_APIError, match="403"):
        await provider._retry_with_backoff(fn)
    assert fn.call_count == 1


@pytest.mark.asyncio
async def test_400_does_not_retry(provider: _StubProvider) -> None:
    fn = AsyncMock(side_effect=_APIError(400))
    with pytest.raises(_APIError, match="400"):
        await provider._retry_with_backoff(fn)
    assert fn.call_count == 1


@pytest.mark.asyncio
@patch("asyncio.sleep", new_callable=AsyncMock)
async def test_max_retries_exhausted(mock_sleep: AsyncMock, provider: _StubProvider) -> None:
    fn = AsyncMock(side_effect=_APIError(429))
    with pytest.raises(_APIError, match="429"):
        await provider._retry_with_backoff(fn)
    assert fn.call_count == 4  # initial + 3 retries


@pytest.mark.asyncio
@patch("asyncio.sleep", new_callable=AsyncMock)
async def test_exponential_backoff_delays(mock_sleep: AsyncMock, provider: _StubProvider) -> None:
    fn = AsyncMock(side_effect=[_APIError(429), _APIError(429), _APIError(429), "ok"])
    await provider._retry_with_backoff(fn)
    delays = [call.args[0] for call in mock_sleep.call_args_list]
    assert delays == [1.0, 2.0, 4.0]
