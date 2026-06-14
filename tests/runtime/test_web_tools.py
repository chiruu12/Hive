"""Tests for WebToolkit — web_fetch and web_search."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import httpx

from hive.tools.web import WebToolkit, _html_to_markdown
from hive.tools.web.toolkit import _validate_url


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

    @patch("hive.tools.web.toolkit._validate_url", return_value=None)
    def test_rate_limit(self, _mock_validate: MagicMock):
        tk = WebToolkit(max_requests_per_cycle=1)
        with patch("hive.tools.web.toolkit.httpx.stream") as mock_stream:
            mock_stream.return_value = _FakeStreamResp(body=b"<p>Hello</p>")
            result1 = tk.web_fetch("https://example.com")
            assert "Hello" in result1

            result2 = tk.web_fetch("https://example.com/2")
            assert "Rate limit" in result2

    @patch("hive.tools.web.toolkit._validate_url", return_value=None)
    @patch("hive.tools.web.toolkit.httpx.stream")
    def test_web_fetch_html(self, mock_stream: MagicMock, _mock_validate: MagicMock):
        mock_stream.return_value = _FakeStreamResp(
            content_type="text/html; charset=utf-8",
            body=b"<html><body><h1>Test Page</h1><p>Content</p></body></html>",
        )
        tk = WebToolkit()
        result = tk.web_fetch("https://example.com")
        assert "Test Page" in result
        assert "Content" in result
        assert "<html>" not in result

    @patch("hive.tools.web.toolkit._validate_url", return_value=None)
    @patch("hive.tools.web.toolkit.httpx.stream")
    def test_web_fetch_plain_text(self, mock_stream: MagicMock, _mock_validate: MagicMock):
        mock_stream.return_value = _FakeStreamResp(
            content_type="text/plain", body=b"Plain text content"
        )
        tk = WebToolkit()
        result = tk.web_fetch("https://example.com/file.txt")
        assert result == "Plain text content"

    @patch("hive.tools.web.toolkit._validate_url", return_value=None)
    @patch("hive.tools.web.toolkit.httpx.stream")
    def test_web_fetch_http_error(self, mock_stream: MagicMock, _mock_validate: MagicMock):
        err_resp = MagicMock()
        err_resp.status_code = 404
        err_resp.reason_phrase = "Not Found"
        mock_stream.return_value = _FakeStreamResp(
            raise_status=httpx.HTTPStatusError("404", request=MagicMock(), response=err_resp)
        )
        tk = WebToolkit()
        result = tk.web_fetch("https://example.com/missing")
        assert "404" in result

    @patch("hive.tools.web.toolkit._validate_url", return_value=None)
    @patch("hive.tools.web.toolkit.httpx.stream")
    def test_web_fetch_body_size_capped(self, mock_stream: MagicMock, _mock_validate: MagicMock):
        from hive.tools.web.toolkit import MAX_CONTENT_CHARS

        mock_stream.return_value = _FakeStreamResp(
            content_type="text/plain", body=b"A" * 100_000
        )
        tk = WebToolkit()
        result = tk.web_fetch("https://example.com/big.txt")
        assert len(result) <= MAX_CONTENT_CHARS


class TestSSRFGuard:
    def test_blocks_non_http_scheme(self):
        assert "Blocked" in (_validate_url("file:///etc/passwd") or "")
        assert "Blocked" in (_validate_url("ftp://example.com") or "")

    def test_blocks_loopback(self):
        assert "Blocked" in (_validate_url("http://localhost/") or "")
        assert "Blocked" in (_validate_url("http://127.0.0.1/") or "")

    def test_blocks_cloud_metadata_ip(self):
        assert "Blocked" in (_validate_url("http://169.254.169.254/latest/meta-data/") or "")

    def test_blocks_private_ranges(self):
        for ip in ("http://10.0.0.5/", "http://192.168.1.1/", "http://172.16.0.1/"):
            assert "Blocked" in (_validate_url(ip) or ""), ip

    def test_allows_public_ip_literal(self):
        # 8.8.8.8 is a global address -- getaddrinfo on a literal needs no DNS.
        assert _validate_url("https://8.8.8.8/") is None

    @patch("hive.tools.web.toolkit.httpx.stream")
    def test_web_fetch_refuses_internal_redirect(self, mock_stream: MagicMock):
        # A public URL that redirects to an internal address must be refused at
        # the second hop, not followed.
        mock_stream.return_value = _FakeStreamResp(
            is_redirect=True, location="http://169.254.169.254/"
        )
        tk = WebToolkit()
        result = tk.web_fetch("https://8.8.8.8/redir")
        assert "Blocked" in result

    @patch("hive.tools.web.toolkit.httpx.get")
    def test_web_search_returns_results(self, mock_get: MagicMock):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = """
        <div class="result">
            <a class="result__title">Python Docs</a>
            <a class="result__url">docs.python.org</a>
            <a class="result__snippet">Official documentation.</a>
        </div>
        """
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        tk = WebToolkit()
        result = tk.web_search("python docs")
        assert "Python Docs" in result
