"""Web browsing toolkit — fetch pages and search the web."""

from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

from hive.tools.base import Toolkit, tool

logger = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 4000
REQUEST_TIMEOUT = 10


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
        try:
            resp = httpx.get(
                url,
                timeout=REQUEST_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": "HiveAgent/1.0"},
            )
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "html" in content_type:
                return _html_to_markdown(resp.text)
            return resp.text[:MAX_CONTENT_CHARS]
        except httpx.HTTPStatusError as e:
            return f"HTTP error {e.response.status_code}: {e.response.reason_phrase}"
        except httpx.RequestError as e:
            return f"Request failed: {e}"

    @tool()
    def web_search(self, query: str) -> str:
        """Search the web using DuckDuckGo and return results.

        Args:
            query: The search query.
        """
        err = self._check_limit()
        if err:
            return err
        try:
            resp = httpx.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": "HiveAgent/1.0"},
                follow_redirects=True,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
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
        except httpx.RequestError as e:
            return f"Search failed: {e}"
