"""Link management toolkit — save, search, and scrape URLs."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from bs4 import BeautifulSoup

from hive.tools.base import Toolkit, tool
from hive.tools.web.toolkit import MAX_CONTENT_CHARS, _html_to_markdown

if TYPE_CHECKING:
    from hive.memory.semantic import SemanticMemory

_LINK_TYPE = "link"
_REQUEST_TIMEOUT = 10
_SUMMARY_CHARS = 500


class LinkToolkit(Toolkit):
    """Tools for saving, searching, and scraping web links.

    Usage:
        # Daemon mode (shared memory):
        tk = LinkToolkit(memory=semantic_memory)

        # Standalone mode (creates own memory):
        tk = LinkToolkit(memory_dir="/path/to/data")
    """

    def __init__(
        self,
        memory: SemanticMemory | None = None,
        memory_dir: str | Path | None = None,
    ):
        self._memory: SemanticMemory | None = None
        self._memory_dir: Path | None = None
        if memory is not None:
            self._memory = memory
        elif memory_dir is not None:
            self._memory_dir = Path(memory_dir)
        else:
            raise ValueError("LinkToolkit requires either memory or memory_dir")

    def bind(self, agent_id: str) -> None:
        super().bind(agent_id)
        if self._memory_dir is not None:
            from hive.memory.semantic import SemanticMemory

            self._memory = SemanticMemory(self._memory_dir, agent_id)

    def rebind(self, agent_id: str) -> None:
        super().rebind(agent_id)
        if self._memory_dir is not None:
            from hive.memory.semantic import SemanticMemory

            self._memory = SemanticMemory(self._memory_dir, agent_id)

    @property
    def instructions(self) -> str:
        return "You can save URLs, search saved links, and scrape web page content."

    @tool()
    async def save_link(self, url: str, tags: str = "", notes: str = "") -> str:
        """Save a URL with auto-scraped title and summary.

        Args:
            url: The URL to save.
            tags: Optional comma-separated tags.
            notes: Optional notes about the link.
        """
        if self._memory is None:
            raise RuntimeError("LinkToolkit is not bound to an agent yet.")

        title = ""
        summary = ""
        try:
            resp = httpx.get(
                url,
                timeout=_REQUEST_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": "HiveAgent/1.0"},
            )
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "html" in content_type:
                soup = BeautifulSoup(resp.text, "html.parser")
                title_tag = soup.find("title")
                if title_tag:
                    title = title_tag.get_text(strip=True)
                summary = _html_to_markdown(resp.text)[:_SUMMARY_CHARS]
            else:
                summary = resp.text[:_SUMMARY_CHARS]
        except (httpx.HTTPError, httpx.RequestError):
            summary = "(could not fetch)"

        thought = f"{title}\n{url}\n{notes}\n{summary}".strip()
        metadata = {
            "type": _LINK_TYPE,
            "url": url,
            "title": title,
            "tags": tags,
        }
        mid = await self._memory.store(thought, metadata)
        display = title or url
        return f"Saved link {mid}: {display}"

    @tool()
    async def search_links(self, query: str, limit: int = 5) -> str:
        """Search saved links by content or tags.

        Args:
            query: Search query.
            limit: Maximum results to return.
        """
        if self._memory is None:
            raise RuntimeError("LinkToolkit is not bound to an agent yet.")

        results = await self._memory.search(query, top_k=limit * 2)
        links = [r for r in results if r.metadata.get("type") == _LINK_TYPE][:limit]
        if not links:
            return "No matching links found."

        lines = []
        for r in links:
            title = r.metadata.get("title", "")
            url = r.metadata.get("url", "")
            tags = r.metadata.get("tags", "")
            display = title or url
            tag_str = f" [{tags}]" if tags else ""
            lines.append(f"- {display}{tag_str}\n  {url}")
        return "\n".join(lines)

    @tool()
    async def list_links(self, limit: int = 10) -> str:
        """List recently saved links.

        Args:
            limit: How many links to show.
        """
        if self._memory is None:
            raise RuntimeError("LinkToolkit is not bound to an agent yet.")

        recent = self._memory.recent(limit * 2)
        links = [r for r in recent if r.metadata.get("type") == _LINK_TYPE][:limit]
        if not links:
            return "No saved links yet."

        lines = []
        for r in links:
            title = r.metadata.get("title", "")
            url = r.metadata.get("url", "")
            ts = r.ts.strftime("%Y-%m-%d %H:%M")
            display = title or url
            lines.append(f"- {display} ({ts})\n  {url}")
        return "\n".join(lines)

    @tool()
    def scrape_link(self, url: str) -> str:
        """Fetch and return the full content of a URL as markdown.

        Args:
            url: The URL to scrape.
        """
        try:
            resp = httpx.get(
                url,
                timeout=_REQUEST_TIMEOUT,
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
