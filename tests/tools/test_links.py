"""Tests for LinkToolkit."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hive.memory.semantic import SemanticMemory
from hive.tools.links.toolkit import LinkToolkit


@pytest.fixture
def memory(tmp_path: Path) -> SemanticMemory:
    return SemanticMemory(tmp_path, "test-agent")


@pytest.fixture
def toolkit(memory: SemanticMemory) -> LinkToolkit:
    tk = LinkToolkit(memory=memory)
    tk.bind("test-agent")
    return tk


class TestLinkToolkit:
    def test_requires_memory_or_dir(self) -> None:
        with pytest.raises(ValueError, match="requires either"):
            LinkToolkit()

    def test_standalone_mode(self, tmp_path: Path) -> None:
        tk = LinkToolkit(memory_dir=tmp_path)
        tk.bind("test-agent")
        assert tk._memory is not None

    @pytest.mark.asyncio
    async def test_save_link(self, toolkit: LinkToolkit) -> None:
        html = '<html><head><title>Test Page</title></head><body><p>Content here</p></body></html>'
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = MagicMock()

        with patch("hive.tools.links.toolkit.httpx.get", return_value=mock_resp):
            result = await toolkit.save_link("https://example.com", tags="test", notes="my note")

        assert "Saved link" in result
        assert "Test Page" in result

    @pytest.mark.asyncio
    async def test_save_link_fetch_failure(self, toolkit: LinkToolkit) -> None:
        import httpx

        with patch(
            "hive.tools.links.toolkit.httpx.get",
            side_effect=httpx.RequestError("timeout"),
        ):
            result = await toolkit.save_link("https://example.com/broken")

        assert "Saved link" in result

    @pytest.mark.asyncio
    async def test_search_links(self, toolkit: LinkToolkit, memory: SemanticMemory) -> None:
        meta = {
            "type": "link", "url": "https://example.com",
            "title": "Example", "tags": "test",
        }
        await memory.store("Example site content", meta)
        await memory.store("Just a regular note", {"type": "note"})

        result = await toolkit.search_links("example")
        assert "Example" in result
        assert "https://example.com" in result

    @pytest.mark.asyncio
    async def test_search_links_empty(self, toolkit: LinkToolkit) -> None:
        result = await toolkit.search_links("nonexistent")
        assert "No matching links" in result

    @pytest.mark.asyncio
    async def test_list_links(self, toolkit: LinkToolkit, memory: SemanticMemory) -> None:
        await memory.store("Site A", {"type": "link", "url": "https://a.com", "title": "A"})
        await memory.store("Not a link", {})

        result = await toolkit.list_links()
        assert "https://a.com" in result

    @pytest.mark.asyncio
    async def test_list_links_empty(self, toolkit: LinkToolkit) -> None:
        result = await toolkit.list_links()
        assert "No saved links" in result

    def test_scrape_link(self, toolkit: LinkToolkit) -> None:
        html = '<html><body><p>Scraped content here.</p></body></html>'
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = MagicMock()

        with patch("hive.tools.links.toolkit.httpx.get", return_value=mock_resp):
            result = toolkit.scrape_link("https://example.com")

        assert "Scraped content here" in result

    def test_scrape_link_error(self, toolkit: LinkToolkit) -> None:
        import httpx

        with patch(
            "hive.tools.links.toolkit.httpx.get",
            side_effect=httpx.RequestError("fail"),
        ):
            result = toolkit.scrape_link("https://example.com/broken")

        assert "Request failed" in result

    def test_not_bound_raises(self) -> None:
        tk = LinkToolkit(memory_dir="/tmp/test")
        with pytest.raises(RuntimeError, match="not bound"):
            import asyncio
            asyncio.run(tk.save_link("https://x.com"))
