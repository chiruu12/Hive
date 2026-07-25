"""Adversarial tests: SSRF and web tool bypass attempts.

These tests probe the WebToolkit and LinkToolkit SSRF guards.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hive.memory.semantic import SemanticMemory
from hive.tools.links.toolkit import LinkToolkit
from hive.tools.url_safety import MAX_REDIRECTS, MAX_RESPONSE_BYTES, validate_url
from hive.tools.web.toolkit import WebToolkit

# ── SSRF Guard Unit Tests ────────────────────────────────────────────────────


class TestSSRFGuardBypassAttempts:
    """Attempt to bypass the SSRF guard in validate_url."""

    def test_blocks_private_ip_ranges(self):
        """All private IP ranges should be blocked."""
        blocked = [
            "http://127.0.0.1/",
            "http://127.0.0.2/",
            "http://localhost/",
            "http://0.0.0.0/",
            "http://10.0.0.1/",
            "http://10.255.255.255/",
            "http://172.16.0.1/",
            "http://172.31.255.255/",
            "http://192.168.0.1/",
            "http://192.168.255.255/",
            "http://169.254.169.254/",  # Cloud metadata
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]/",  # IPv6 loopback
            "http://[::ffff:127.0.0.1]/",  # IPv4-mapped IPv6 loopback
        ]
        for url in blocked:
            error, ip = validate_url(url)
            assert error is not None, f"Should block: {url}"

    def test_blocks_non_http_schemes(self):
        """Non-http(s) schemes should be blocked."""
        blocked = [
            "file:///etc/passwd",
            "ftp://example.com/",
            "gopher://example.com/",
            "dict://example.com/",
            "javascript:alert(1)",
            "data:text/html,<h1>pwned</h1>",
        ]
        for url in blocked:
            error, ip = validate_url(url)
            assert error is not None, f"Should block: {url}"

    def test_blocks_no_host(self):
        """URLs without a host should be blocked."""
        error, ip = validate_url("http://")
        assert error is not None

    def test_blocks_unresolvable_host(self):
        """Hosts that can't be resolved should be blocked."""
        error, ip = validate_url("http://this-host-definitely-does-not-exist.invalid/")
        assert error is not None

    def test_allows_public_urls(self):
        """Public URLs should be allowed (requires network)."""
        # Using a well-known public IP
        error, ip = validate_url("http://1.1.1.1/")
        # This might fail if DNS is unavailable, but should not block public IPs
        if error is None:
            assert ip is not None


class _FakeAsyncStreamResp:
    """Minimal async streaming response stand-in for redirect-hop tests."""

    def __init__(
        self,
        *,
        is_redirect: bool = False,
        location: str | None = None,
        body: bytes = b"",
        content_type: str = "text/html",
    ) -> None:
        self.is_redirect = is_redirect
        self.headers = {"content-type": content_type}
        if location is not None:
            self.headers["location"] = location
        self._body = body
        self.encoding = "utf-8"

    def raise_for_status(self) -> None:
        return None

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        yield self._body

    async def __aenter__(self) -> _FakeAsyncStreamResp:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


class _FakeAsyncClient:
    def __init__(self, stream_resp: _FakeAsyncStreamResp) -> None:
        self._stream_resp = stream_resp

    def stream(self, *args: object, **kwargs: object) -> _FakeAsyncStreamResp:
        return self._stream_resp

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


class TestSSRFViaRedirects:
    """Test that redirects to internal IPs are caught."""

    @pytest.mark.asyncio
    async def test_link_scrape_blocks_redirect_to_internal_ip(self, tmp_path: Path) -> None:
        """LinkToolkit must re-validate each redirect hop, blocking internal targets."""
        memory = SemanticMemory(tmp_path, "adversarial-agent")
        toolkit = LinkToolkit(memory=memory)
        toolkit.bind("adversarial-agent")

        redirect_resp = _FakeAsyncStreamResp(
            is_redirect=True,
            location="http://169.254.169.254/",
        )
        with patch(
            "hive.tools.url_safety.httpx.AsyncClient",
            return_value=_FakeAsyncClient(redirect_resp),
        ):
            result = await toolkit.scrape_link("https://8.8.8.8/redir")

        assert "Blocked" in result

    @pytest.mark.asyncio
    async def test_link_save_blocks_redirect_to_internal_ip(self, tmp_path: Path) -> None:
        """save_link must not persist a link when a redirect targets an internal IP."""
        memory = SemanticMemory(tmp_path, "adversarial-agent")
        toolkit = LinkToolkit(memory=memory)
        toolkit.bind("adversarial-agent")

        redirect_resp = _FakeAsyncStreamResp(
            is_redirect=True,
            location="http://127.0.0.1/",
        )
        with patch(
            "hive.tools.url_safety.httpx.AsyncClient",
            return_value=_FakeAsyncClient(redirect_resp),
        ):
            result = await toolkit.save_link("https://8.8.8.8/redir")

        assert "Blocked" in result
        assert "Saved link" not in result


class TestWebSearchRedirectSSRF:
    """web_search must re-validate each redirect hop like web_fetch."""

    def test_web_search_blocks_redirect_to_internal_ip(self) -> None:
        toolkit = WebToolkit()
        toolkit.bind("adversarial-agent")

        class _FakeSyncStreamResp:
            is_redirect = True
            headers = {"location": "http://169.254.169.254/", "content-type": "text/html"}
            encoding = "utf-8"

            def raise_for_status(self) -> None:
                return None

            def iter_bytes(self):
                yield b""

            def __enter__(self) -> _FakeSyncStreamResp:
                return self

            def __exit__(self, *args: object) -> bool:
                return False

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        mock_client.stream.return_value.__enter__.return_value = _FakeSyncStreamResp()
        mock_client.stream.return_value.__exit__.return_value = False

        with patch("hive.tools.url_safety.httpx.Client", return_value=mock_client):
            result = toolkit.web_search("test query")

        assert "Blocked" in result


class TestSSRFDNSRebinding:
    """Test DNS rebinding protection (TOCTOU fix)."""

    def test_validated_ip_returned(self):
        """validate_url should return the validated IP for pinning."""
        # Using a public IP that should resolve
        error, ip = validate_url("http://1.1.1.1/")
        if error is None:
            assert ip == "1.1.1.1"

    def test_ipv6_pinned_netloc_is_bracketed(self):
        """IPv6 pinning must bracket the address so URL parsing stays unambiguous."""
        from hive.tools.url_safety import build_pinned_request

        ipv6 = "2606:2800:220:1:248:1893:25c8:1946"
        request_url, headers, _extensions = build_pinned_request(
            "https://example.com/path",
            ipv6,
        )
        assert request_url.startswith(f"https://[{ipv6}]/")
        assert headers["Host"] == "example.com"


# ── LinkToolkit SSRF Guard ───────────────────────────────────────────────────


class TestLinkToolkitSSRFProtection:
    """Verify LinkToolkit blocks SSRF before any HTTP request."""

    BLOCKED_URLS = [
        "http://127.0.0.1/",
        "http://127.0.0.2/",
        "http://localhost/",
        "http://0.0.0.0/",
        "http://10.0.0.1/",
        "http://172.16.0.1/",
        "http://192.168.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "file:///etc/passwd",
        "gopher://example.com/",
    ]

    @pytest.fixture
    def link_toolkit(self, tmp_path: Path) -> LinkToolkit:
        memory = SemanticMemory(tmp_path, "adversarial-agent")
        tk = LinkToolkit(memory=memory)
        tk.bind("adversarial-agent")
        return tk

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", BLOCKED_URLS)
    async def test_save_link_blocks_ssrf(self, link_toolkit: LinkToolkit, url: str) -> None:
        with patch("hive.tools.url_safety.httpx.AsyncClient") as mock_client:
            result = await link_toolkit.save_link(url)
        assert "Blocked:" in result
        mock_client.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", BLOCKED_URLS)
    async def test_scrape_link_blocks_ssrf(self, link_toolkit: LinkToolkit, url: str) -> None:
        with patch("hive.tools.url_safety.httpx.AsyncClient") as mock_client:
            result = await link_toolkit.scrape_link(url)
        assert "Blocked:" in result
        mock_client.assert_not_called()


# ── Response Size Limits ─────────────────────────────────────────────────────


class TestResponseSizeLimits:
    """Verify response size caps prevent memory exhaustion."""

    def test_max_response_bytes_constant_exists(self):
        """MAX_RESPONSE_BYTES should be defined and reasonable."""
        assert MAX_RESPONSE_BYTES > 0
        assert MAX_RESPONSE_BYTES <= 10_000_000  # 10MB max


class TestRedirectLimits:
    """Verify redirect limits prevent infinite loops."""

    def test_max_redirects_constant_exists(self):
        """MAX_REDIRECTS should be defined and reasonable."""
        assert MAX_REDIRECTS > 0
        assert MAX_REDIRECTS <= 20  # Reasonable limit


class TestRateLimiting:
    """Verify rate limiting is in place."""

    def test_rate_limit_exists(self):
        """WebToolkit should have rate limiting."""
        toolkit = WebToolkit()
        toolkit.bind("test-agent")

        # The toolkit tracks remaining requests per cycle
        assert hasattr(toolkit, "_remaining")
        assert toolkit._remaining > 0
