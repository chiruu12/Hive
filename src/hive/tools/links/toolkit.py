"""Link management toolkit — save, search, and scrape URLs."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from bs4 import BeautifulSoup

from hive.tools.base import Toolkit, tool
from hive.tools.links.store import NamedLinkStore
from hive.tools.web.toolkit import MAX_CONTENT_CHARS, _html_to_markdown

if TYPE_CHECKING:
    from hive.memory.semantic import SemanticMemory

_LINK_TYPE = "link"
_REQUEST_TIMEOUT = 10
_SUMMARY_CHARS = 500


class LinkToolkit(Toolkit):
    """Tools for saving, searching, and scraping web links.

    Two kinds of links are supported:

    - **Search-based links** (``save_link`` / ``search_links`` / ``list_links``)
      are stored in semantic memory with an auto-scraped title and summary.
    - **Named links** (``save_named_link`` / ``get_named_link`` /
      ``list_named_links`` / ``remove_named_link``) are a stable, exact,
      enumerable ``name -> URL`` map backed by a JSON file -- the model a host
      app wants for "save my github as X" / "open my github". The file is the
      single source of truth a host can also read/write directly via
      :class:`~hive.tools.links.store.NamedLinkStore`.

    Usage:
        # Daemon mode (shared memory):
        tk = LinkToolkit(memory=semantic_memory)

        # Standalone mode (creates own memory):
        tk = LinkToolkit(memory_dir="/path/to/data")

        # Point the named-link store at a host-owned path:
        tk = LinkToolkit(memory=mem, named_links_path="~/.nudge/data/links.json")
    """

    def __init__(
        self,
        memory: SemanticMemory | None = None,
        memory_dir: str | Path | None = None,
        named_links_path: str | Path | None = None,
    ):
        self._memory: SemanticMemory | None = None
        self._memory_dir: Path | None = None
        if memory is not None:
            self._memory = memory
        elif memory_dir is not None:
            self._memory_dir = Path(memory_dir)
        else:
            raise ValueError("LinkToolkit requires either memory or memory_dir")
        self._named_links_path = Path(named_links_path) if named_links_path else None
        self._named_store: NamedLinkStore | None = None

    def bind(self, agent_id: str) -> None:
        super().bind(agent_id)
        if self._memory_dir is not None:
            from hive.memory.semantic import SemanticMemory

            self._memory = SemanticMemory(self._memory_dir, agent_id)
        self._named_store = None  # re-resolve lazily for the bound agent

    def rebind(self, agent_id: str) -> None:
        super().rebind(agent_id)
        if self._memory_dir is not None:
            from hive.memory.semantic import SemanticMemory

            self._memory = SemanticMemory(self._memory_dir, agent_id)
        self._named_store = None

    def _named(self) -> NamedLinkStore:
        """Resolve (lazily) the named-link store for the current binding.

        Path precedence: an explicit ``named_links_path`` (host-owned), else
        ``<memory_dir>/named_links.json``, else co-located with the agent's
        semantic memory (``<memory.storage_dir>/named_links.json``).
        """
        if self._named_store is not None:
            return self._named_store
        if self._named_links_path is not None:
            path = self._named_links_path
        elif self._memory_dir is not None:
            path = self._memory_dir / "named_links.json"
        elif self._memory is not None:
            path = self._memory.storage_dir / "named_links.json"
        else:
            raise RuntimeError("LinkToolkit is not bound to an agent yet.")
        self._named_store = NamedLinkStore(path)
        return self._named_store

    @property
    def instructions(self) -> str:
        return (
            "You can save URLs, search saved links, and scrape web page content. "
            "You can also manage named links -- a stable name -> URL map -- with "
            "save_named_link, get_named_link, list_named_links, and remove_named_link."
        )

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
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                resp = await client.get(
                    url,
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
    async def search_links(self, query: str, limit: str = "5") -> str:
        """Search saved links by content or tags.

        Args:
            query: Search query.
            limit: Maximum results to return.
        """
        if self._memory is None:
            raise RuntimeError("LinkToolkit is not bound to an agent yet.")

        n = int(float(limit))
        results = await self._memory.search(query, top_k=n * 2)
        links = [r for r in results if r.metadata.get("type") == _LINK_TYPE][:n]
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
    async def list_links(self, limit: str = "10") -> str:
        """List recently saved links.

        Args:
            limit: How many links to show.
        """
        if self._memory is None:
            raise RuntimeError("LinkToolkit is not bound to an agent yet.")

        n = int(float(limit))
        recent = self._memory.recent(n * 2)
        links = [r for r in recent if r.metadata.get("type") == _LINK_TYPE][:n]
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
    async def scrape_link(self, url: str) -> str:
        """Fetch and return the full content of a URL as markdown.

        Args:
            url: The URL to scrape.
        """
        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                resp = await client.get(
                    url,
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
    async def save_named_link(self, name: str, url: str) -> str:
        """Save (or update) a named link for exact lookup by name later.

        Args:
            name: A short name, e.g. "github". Reusing a name overwrites it.
            url: The URL (must start with http:// or https://).
        """
        try:
            link = self._named().save(name, url)
        except ValueError as e:
            return f"Error: {e}"
        return f"Saved named link '{link.name}' -> {link.url}"

    @tool()
    async def get_named_link(self, name: str) -> str:
        """Look up a saved named link by its name.

        Args:
            name: The link name to look up.
        """
        url = self._named().get(name)
        return url if url is not None else f"No named link found for '{name}'."

    @tool()
    async def list_named_links(self) -> str:
        """List all saved named links."""
        links = self._named().list()
        if not links:
            return "No named links saved yet."
        return "\n".join(f"- {entry['name']}: {entry['url']}" for entry in links)

    @tool()
    async def remove_named_link(self, name: str) -> str:
        """Remove a saved named link by its name.

        Args:
            name: The link name to remove.
        """
        removed = self._named().remove(name)
        if removed:
            return f"Removed named link '{name}'."
        return f"No named link found for '{name}'."
