"""Tests for WebToolkit — web_fetch and web_search."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import httpx

from hive.tools.url_safety import SafeFetchResult, validate_url
from hive.tools.web import WebToolkit, _html_to_markdown


class _FakeStreamResp:
    """Minimal stand-in for an httpx streaming Response used as a CM."""

    def __init__(
        self,
        *,
        content_type: str = "text/html",
        body: bytes = b"",
        is_redirect: bool = False,
        location: str | None = None,
        raise_status: Exception | None = None,
        encoding: str = "utf-8",
    ) -> None:
        self.is_redirect = is_redirect
        self.headers = {"content-type": content_type}
        if location is not None:
            self.headers["location"] = location
        self._body = body
        self.encoding = encoding
        self._raise = raise_status
        self.url = httpx.URL("https://example.com")

    def raise_for_status(self) -> None:
        if self._raise:
            raise self._raise

    def iter_bytes(self) -> Iterator[bytes]:
        yield self._body

    def __enter__(self) -> _FakeStreamResp:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class TestHtmlToMarkdown:
    def test_strips_tags(self):
        html = "<html><body><h1>Title</h1><p>Text here</p></body></html>"
        result = _html_to_markdown(html)
        assert "Title" in result
        assert "Text here" in result
        assert "<h1>" not in result

    def test_removes_script_and_style(self):
        html = "<script>alert('x')</script><style>.x{}</style><p>Keep</p>"
        result = _html_to_markdown(html)
        assert "alert" not in result
        assert "Keep" in result

    def test_truncates_long_content(self):
        html = "<p>" + "A" * 10000 + "</p>"
        result = _html_to_markdown(html)
        assert len(result) <= 4000


class TestWebToolkit:
    def test_tool_discovery(self):
        tk = WebToolkit()
        tools = tk.get_tools()
        names = {t.name for t in tools}
        assert "web_fetch" in names
        assert "web_search" in names

    @patch(
        "hive.tools.web.toolkit.fetch_url_safe_sync",
        return_value=SafeFetchResult(ok=True, text="<p>Hello</p>", content_type="text/html"),
    )
    def test_rate_limit(self, _mock_fetch: MagicMock):
        tk = WebToolkit(max_requests_per_cycle=1)
        result1 = tk.web_fetch("https://example.com")
        assert "Hello" in result1

        result2 = tk.web_fetch("https://example.com/2")
        assert "Rate limit" in result2

    @patch(
        "hive.tools.web.toolkit.fetch_url_safe_sync",
        return_value=SafeFetchResult(
            ok=True,
            text="<html><body><h1>Test Page</h1><p>Content</p></body></html>",
            content_type="text/html; charset=utf-8",
        ),
    )
    def test_web_fetch_html(self, _mock_fetch: MagicMock):
        tk = WebToolkit()
        result = tk.web_fetch("https://example.com")
        assert "Test Page" in result
        assert "Content" in result
        assert "<html>" not in result

    @patch(
        "hive.tools.web.toolkit.fetch_url_safe_sync",
        return_value=SafeFetchResult(ok=True, text="Plain text content", content_type="text/plain"),
    )
    def test_web_fetch_plain_text(self, _mock_fetch: MagicMock):
        tk = WebToolkit()
        result = tk.web_fetch("https://example.com/file.txt")
        assert result == "Plain text content"

    @patch(
        "hive.tools.web.toolkit.fetch_url_safe_sync",
        return_value=SafeFetchResult(ok=False, error="HTTP error 404: Not Found"),
    )
    def test_web_fetch_http_error(self, _mock_fetch: MagicMock):
        tk = WebToolkit()
        result = tk.web_fetch("https://example.com/missing")
        assert "404" in result

    @patch(
        "hive.tools.web.toolkit.fetch_url_safe_sync",
        return_value=SafeFetchResult(ok=True, text="A" * 100_000, content_type="text/plain"),
    )
    def test_web_fetch_body_size_capped(self, _mock_fetch: MagicMock):
        from hive.tools.web.toolkit import MAX_CONTENT_CHARS

        tk = WebToolkit()
        result = tk.web_fetch("https://example.com/big.txt")
        assert len(result) <= MAX_CONTENT_CHARS


class TestSSRFGuard:
    def test_blocks_non_http_scheme(self):
        assert "Blocked" in (validate_url("file:///etc/passwd")[0] or "")
        assert "Blocked" in (validate_url("ftp://example.com")[0] or "")

    def test_blocks_loopback(self):
        assert "Blocked" in (validate_url("http://localhost/")[0] or "")
        assert "Blocked" in (validate_url("http://127.0.0.1/")[0] or "")

    def test_blocks_cloud_metadata_ip(self):
        assert "Blocked" in (validate_url("http://169.254.169.254/latest/meta-data/")[0] or "")

    def test_blocks_private_ranges(self):
        for ip in ("http://10.0.0.5/", "http://192.168.1.1/", "http://172.16.0.1/"):
            assert "Blocked" in (validate_url(ip)[0] or ""), ip

    def test_allows_public_ip_literal(self):
        # 8.8.8.8 is a global address -- getaddrinfo on a literal needs no DNS.
        err, ip = validate_url("https://8.8.8.8/")
        assert err is None
        assert ip == "8.8.8.8"

    def test_returns_validated_ip_for_pinning(self):
        # The caller pins the connection to this IP to close the DNS-rebinding
        # TOCTOU window, so a public host must yield a concrete address.
        err, ip = validate_url("http://93.184.216.34/")
        assert err is None
        assert ip == "93.184.216.34"

    def test_https_pins_ip_and_sets_sni_hostname(self):
        from hive.tools.url_safety import build_pinned_request

        request_url, headers, extensions = build_pinned_request(
            "https://example.com/path",
            "93.184.216.34",
        )
        assert request_url.startswith("https://93.184.216.34/")
        assert headers["Host"] == "example.com"
        assert extensions["sni_hostname"] == b"example.com"

    def test_https_ipv6_pins_bracketed_netloc(self):
        from hive.tools.url_safety import build_pinned_request

        ipv6 = "2606:2800:220:1:248:1893:25c8:1946"
        request_url, headers, extensions = build_pinned_request(
            "https://example.com:8443/path",
            ipv6,
        )
        assert request_url.startswith(f"https://[{ipv6}]:8443/")
        assert headers["Host"] == "example.com:8443"
        assert extensions["sni_hostname"] == b"example.com"

    @patch("hive.tools.url_safety.httpx.Client")
    def test_web_fetch_refuses_internal_redirect(self, mock_client_cls: MagicMock):
        # A public URL that redirects to an internal address must be refused at
        # the second hop, not followed.
        fake_resp = _FakeStreamResp(is_redirect=True, location="http://169.254.169.254/")
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        mock_client.stream.return_value.__enter__.return_value = fake_resp
        mock_client.stream.return_value.__exit__.return_value = False
        mock_client_cls.return_value = mock_client

        tk = WebToolkit()
        result = tk.web_fetch("https://8.8.8.8/redir")
        assert "Blocked" in result

    @patch(
        "hive.tools.web.toolkit.request_url_safe_sync",
        return_value=SafeFetchResult(
            ok=True,
            text="""
        <div class="result">
            <a class="result__title">Python Docs</a>
            <a class="result__url">docs.python.org</a>
            <a class="result__snippet">Official documentation.</a>
        </div>
        """,
            content_type="text/html",
        ),
    )
    def test_web_search_returns_results(self, _mock_request: MagicMock):
        tk = WebToolkit()
        result = tk.web_search("python docs")
        assert "Python Docs" in result
