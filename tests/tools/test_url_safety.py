"""Tests that safe URL fetch passes IP pinning through to httpx.stream()."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from unittest.mock import MagicMock, patch

import pytest

from hive.tools.url_safety import fetch_url_safe, request_url_safe_sync


class _FakeSyncStreamResp:
    """Minimal stand-in for an httpx streaming Response used as a CM."""

    is_redirect = False
    headers = {"content-type": "text/plain"}
    encoding = "utf-8"

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self) -> Iterator[bytes]:
        yield b"ok"

    def __enter__(self) -> _FakeSyncStreamResp:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class _FakeAsyncStreamResp:
    """Minimal async streaming response stand-in."""

    is_redirect = False
    headers = {"content-type": "text/plain"}
    encoding = "utf-8"

    def raise_for_status(self) -> None:
        return None

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        yield b"ok"

    async def __aenter__(self) -> _FakeAsyncStreamResp:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


@patch(
    "hive.tools.url_safety.validate_url",
    return_value=(None, "93.184.216.34"),
)
@patch("hive.tools.url_safety.httpx.Client")
def test_request_url_safe_sync_passes_pinned_args_to_stream(
    mock_client_cls: MagicMock,
    _mock_validate: MagicMock,
) -> None:
    """Sync fetch must pass pinned URL, Host header, and SNI to httpx.stream()."""
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.stream.return_value.__enter__.return_value = _FakeSyncStreamResp()
    mock_client.stream.return_value.__exit__.return_value = False
    mock_client_cls.return_value = mock_client

    result = request_url_safe_sync("https://example.com/path?q=1")

    assert result.ok
    mock_client.stream.assert_called_once()
    args, kwargs = mock_client.stream.call_args
    assert args[0] == "GET"
    assert args[1].startswith("https://93.184.216.34/")
    assert kwargs["follow_redirects"] is False
    assert kwargs["headers"]["Host"] == "example.com"
    assert kwargs["extensions"]["sni_hostname"] == b"example.com"


@patch(
    "hive.tools.url_safety.validate_url",
    return_value=(None, "93.184.216.34"),
)
@patch("hive.tools.url_safety.httpx.Client")
def test_request_url_safe_sync_http_pins_ip_without_sni(
    mock_client_cls: MagicMock,
    _mock_validate: MagicMock,
) -> None:
    """HTTP fetch must pin IP in netloc and set Host, but not SNI."""
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.stream.return_value.__enter__.return_value = _FakeSyncStreamResp()
    mock_client.stream.return_value.__exit__.return_value = False
    mock_client_cls.return_value = mock_client

    result = request_url_safe_sync("http://example.com/path")

    assert result.ok
    args, kwargs = mock_client.stream.call_args
    assert args[1].startswith("http://93.184.216.34/")
    assert kwargs["headers"]["Host"] == "example.com"
    assert "sni_hostname" not in (kwargs.get("extensions") or {})


class _RecordingAsyncClient:
    """Fake AsyncClient that records stream() kwargs."""

    def __init__(self, stream_resp: _FakeAsyncStreamResp) -> None:
        self._stream_resp = stream_resp
        self.stream_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def stream(self, *args: object, **kwargs: object) -> _FakeAsyncStreamResp:
        self.stream_calls.append((args, kwargs))
        return self._stream_resp

    async def __aenter__(self) -> _RecordingAsyncClient:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


@patch(
    "hive.tools.url_safety.validate_url",
    return_value=(None, "93.184.216.34"),
)
@patch("hive.tools.url_safety.httpx.AsyncClient")
@pytest.mark.asyncio
async def test_fetch_url_safe_passes_pinned_args_to_stream(
    mock_client_cls: MagicMock,
    _mock_validate: MagicMock,
) -> None:
    """Async fetch must pass pinned URL, Host header, and SNI to httpx.stream()."""
    fake_client = _RecordingAsyncClient(_FakeAsyncStreamResp())
    mock_client_cls.return_value = fake_client

    result = await fetch_url_safe("https://example.com:8443/secure")

    assert result.ok
    assert len(fake_client.stream_calls) == 1
    args, kwargs = fake_client.stream_calls[0]
    assert args[0] == "GET"
    assert args[1].startswith("https://93.184.216.34:8443/")
    assert kwargs["follow_redirects"] is False
    assert kwargs["headers"]["Host"] == "example.com:8443"
    assert kwargs["extensions"]["sni_hostname"] == b"example.com"


@patch(
    "hive.tools.url_safety.validate_url",
    return_value=(None, "2606:2800:220:1:248:1893:25c8:1946"),
)
@patch("hive.tools.url_safety.httpx.Client")
def test_request_url_safe_sync_ipv6_pinned_url(
    mock_client_cls: MagicMock,
    _mock_validate: MagicMock,
) -> None:
    """IPv6 validated addresses must appear bracketed in the pinned netloc."""
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.stream.return_value.__enter__.return_value = _FakeSyncStreamResp()
    mock_client.stream.return_value.__exit__.return_value = False
    mock_client_cls.return_value = mock_client

    result = request_url_safe_sync("https://example.com/")

    assert result.ok
    args, kwargs = mock_client.stream.call_args
    assert args[1].startswith("https://[2606:2800:220:1:248:1893:25c8:1946]/")
    assert kwargs["headers"]["Host"] == "example.com"
    assert kwargs["extensions"]["sni_hostname"] == b"example.com"
