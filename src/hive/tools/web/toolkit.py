"""Web browsing toolkit — fetch pages and search the web."""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from hive.tools.base import Toolkit, tool
from hive.tools.url_safety import (
    MAX_REDIRECTS,
    REQUEST_TIMEOUT,
    fetch_url_safe_sync,
    request_url_safe_sync,
)

logger = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 4000


def _html_to_markdown(html: str) -> str:
    """Strip HTML to readable plain text / rough markdown."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:MAX_CONTENT_CHARS]


class WebToolkit(Toolkit):
    """Tools for fetching web pages and searching the internet."""

    def __init__(self, max_requests_per_cycle: int = 10):
        self._remaining = max_requests_per_cycle

    def _check_limit(self) -> str | None:
        if self._remaining <= 0:
            return "Rate limit reached. No more web requests this cycle."
        self._remaining -= 1
        return None

    @tool()
    def web_fetch(self, url: str) -> str:
        """Fetch a web page and return its content as readable text.

        Args:
            url: The URL to fetch.
        """
        err = self._check_limit()
        if err:
            return err
        result = fetch_url_safe_sync(url, timeout=REQUEST_TIMEOUT, max_redirects=MAX_REDIRECTS)
        if not result.ok:
            return result.error or "Request failed."
        if "html" in result.content_type:
            return _html_to_markdown(result.text)
        return result.text[:MAX_CONTENT_CHARS]

    @tool()
    def web_search(self, query: str) -> str:
        """Search the web using DuckDuckGo and return results.

        Args:
            query: The search query.
        """
        err = self._check_limit()
        if err:
            return err
        result = request_url_safe_sync(
            "https://html.duckduckgo.com/html/",
            method="POST",
            data={"q": query},
            timeout=REQUEST_TIMEOUT,
            max_redirects=MAX_REDIRECTS,
        )
        if not result.ok:
            return result.error or "Search failed."
        try:
            soup = BeautifulSoup(result.text, "html.parser")
            results = []
            for r in soup.select(".result")[:5]:
                title_el = r.select_one(".result__title")
                snippet_el = r.select_one(".result__snippet")
                link_el = r.select_one(".result__url")
                title = title_el.get_text(strip=True) if title_el else ""
                snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                link = link_el.get_text(strip=True) if link_el else ""
                if title:
                    results.append(f"- {title}\n  {link}\n  {snippet}")
            return "\n\n".join(results) if results else "No results found."
        except Exception as e:
            return f"Search failed: {e}"
