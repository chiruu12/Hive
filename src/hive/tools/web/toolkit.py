"""Web browsing toolkit — fetch pages and search the web."""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from hive.tools.base import Toolkit, tool

logger = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 4000
REQUEST_TIMEOUT = 10
MAX_REDIRECTS = 5
# Hard cap on bytes read off the wire before decoding -- prevents a huge or
# never-ending response from exhausting memory (the text is truncated to
# MAX_CONTENT_CHARS afterwards anyway).
MAX_RESPONSE_BYTES = 5_000_000


def _validate_url(url: str) -> str | None:
    """Return an error string if ``url`` is unsafe to fetch (SSRF guard), else None.

    Rejects non-http(s) schemes and any host that resolves to a non-public
    address (loopback, private, link-local incl. the cloud metadata IP
    169.254.169.254, reserved, multicast, or unspecified).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Blocked: only http/https URLs are allowed (got '{parsed.scheme or 'none'}')."
    host = parsed.hostname
    if not host:
        return "Blocked: URL has no host."
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        return f"Blocked: cannot resolve host '{host}': {e}"
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return f"Blocked: '{host}' resolves to a non-public address ({ip})."
    return None


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
        # Redirects are followed manually so each hop is re-validated -- otherwise
        # a public URL could redirect to an internal/metadata address (SSRF).
        try:
            current = url
            for _ in range(MAX_REDIRECTS + 1):
                blocked = _validate_url(current)
                if blocked:
                    return blocked
                with httpx.stream(
                    "GET",
                    current,
                    timeout=REQUEST_TIMEOUT,
                    follow_redirects=False,
                    headers={"User-Agent": "HiveAgent/1.0"},
                ) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location")
                        if not location:
                            break
                        current = str(resp.url.join(location))
                        continue
                    resp.raise_for_status()
                    content_type = resp.headers.get("content-type", "")
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in resp.iter_bytes():
                        chunks.append(chunk)
                        total += len(chunk)
                        if total >= MAX_RESPONSE_BYTES:
                            break
                    text = b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")
                    if "html" in content_type:
                        return _html_to_markdown(text)
                    return text[:MAX_CONTENT_CHARS]
            return "Blocked: too many redirects."
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
