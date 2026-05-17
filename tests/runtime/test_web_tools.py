"""Tests for WebToolkit — web_fetch and web_search."""

from unittest.mock import MagicMock, patch

from hive.tools.web import WebToolkit, _html_to_markdown


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

    def test_rate_limit(self):
        tk = WebToolkit(max_requests_per_cycle=1)
        with patch("hive.tools.web.toolkit.httpx.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.headers = {"content-type": "text/html"}
            mock_resp.text = "<p>Hello</p>"
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            result1 = tk.web_fetch("https://example.com")
            assert "Hello" in result1

            result2 = tk.web_fetch("https://example.com/2")
            assert "Rate limit" in result2

    @patch("hive.tools.web.toolkit.httpx.get")
    def test_web_fetch_html(self, mock_get: MagicMock):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
        mock_resp.text = "<html><body><h1>Test Page</h1><p>Content</p></body></html>"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        tk = WebToolkit()
        result = tk.web_fetch("https://example.com")
        assert "Test Page" in result
        assert "Content" in result
        assert "<html>" not in result

    @patch("hive.tools.web.toolkit.httpx.get")
    def test_web_fetch_plain_text(self, mock_get: MagicMock):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/plain"}
        mock_resp.text = "Plain text content"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        tk = WebToolkit()
        result = tk.web_fetch("https://example.com/file.txt")
        assert result == "Plain text content"

    @patch("hive.tools.web.toolkit.httpx.get")
    def test_web_fetch_http_error(self, mock_get: MagicMock):
        import httpx

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.reason_phrase = "Not Found"
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=mock_resp
        )
        mock_get.return_value = mock_resp

        tk = WebToolkit()
        result = tk.web_fetch("https://example.com/missing")
        assert "404" in result

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
