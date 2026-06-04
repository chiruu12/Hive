"""Tests for the named-link store and LinkToolkit's named-link tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from hive.memory.semantic import SemanticMemory
from hive.tools.links import NamedLink, NamedLinkStore, normalize_name
from hive.tools.links.toolkit import LinkToolkit


class TestNormalizeName:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("github", "github"),
            ("My GitHub", "my-github"),
            ("my_github", "my-github"),
            ("  My   Git Hub  ", "my-git-hub"),
            ("my--github", "my-github"),
            ("GitHub_Profile Page", "github-profile-page"),
        ],
    )
    def test_normalizes_to_stable_key(self, raw: str, expected: str) -> None:
        assert normalize_name(raw) == expected


class TestNamedLinkStore:
    def test_save_and_get(self, tmp_path: Path) -> None:
        store = NamedLinkStore(tmp_path / "links.json")
        link = store.save("GitHub", "https://github.com/me")
        assert link == NamedLink(name="GitHub", url="https://github.com/me")
        # Exact lookup is by normalized name.
        assert store.get("github") == "https://github.com/me"
        assert store.get("GitHub") == "https://github.com/me"
        assert store.get("my_github") is None

    def test_save_upserts(self, tmp_path: Path) -> None:
        store = NamedLinkStore(tmp_path / "links.json")
        store.save("github", "https://github.com/old")
        store.save("GitHub", "https://github.com/new")
        assert store.get("github") == "https://github.com/new"
        assert len(store.list()) == 1

    @pytest.mark.parametrize("bad_url", ["github.com", "ftp://x", "", "javascript:alert(1)"])
    def test_rejects_non_http_url(self, tmp_path: Path, bad_url: str) -> None:
        store = NamedLinkStore(tmp_path / "links.json")
        with pytest.raises(ValueError, match="http"):
            store.save("x", bad_url)

    def test_rejects_empty_name(self, tmp_path: Path) -> None:
        store = NamedLinkStore(tmp_path / "links.json")
        with pytest.raises(ValueError, match="name"):
            store.save("   ", "https://example.com")

    def test_list_is_deterministic(self, tmp_path: Path) -> None:
        store = NamedLinkStore(tmp_path / "links.json")
        store.save("zeta", "https://z.com")
        store.save("Alpha", "https://a.com")
        listed = store.list()
        assert [e["name"] for e in listed] == ["Alpha", "zeta"]
        assert listed[0] == {"name": "Alpha", "url": "https://a.com"}

    def test_remove(self, tmp_path: Path) -> None:
        store = NamedLinkStore(tmp_path / "links.json")
        store.save("github", "https://github.com/me")
        assert store.remove("GitHub") is True
        assert store.get("github") is None
        assert store.remove("github") is False  # already gone

    def test_persists_across_instances(self, tmp_path: Path) -> None:
        path = tmp_path / "links.json"
        NamedLinkStore(path).save("github", "https://github.com/me")
        assert NamedLinkStore(path).get("github") == "https://github.com/me"

    def test_corrupt_file_recovery(self, tmp_path: Path) -> None:
        path = tmp_path / "links.json"
        path.write_text("{ this is not valid json ]")
        store = NamedLinkStore(path)
        # Reads recover to an empty store and back up the bad file.
        assert store.list() == []
        assert path.with_suffix(".json.corrupt").exists()
        # The store is usable again afterward.
        store.save("github", "https://github.com/me")
        assert NamedLinkStore(path).get("github") == "https://github.com/me"


class TestLinkToolkitNamedLinks:
    @pytest.fixture
    def toolkit(self, tmp_path: Path) -> LinkToolkit:
        memory = SemanticMemory(tmp_path, "test-agent")
        tk = LinkToolkit(memory=memory)
        tk.bind("test-agent")
        return tk

    @pytest.mark.asyncio
    async def test_tools_share_one_store_with_host(self, tmp_path: Path) -> None:
        # A host points the toolkit at its own path and reads the same store.
        host_path = tmp_path / "host" / "links.json"
        memory = SemanticMemory(tmp_path, "test-agent")
        tk = LinkToolkit(memory=memory, named_links_path=host_path)
        tk.bind("test-agent")

        await tk.save_named_link("GitHub", "https://github.com/me")

        host_store = NamedLinkStore(host_path)
        assert host_store.get("github") == "https://github.com/me"

    @pytest.mark.asyncio
    async def test_save_get_list_remove(self, toolkit: LinkToolkit) -> None:
        assert "Saved" in await toolkit.save_named_link("github", "https://github.com/me")
        assert await toolkit.get_named_link("github") == "https://github.com/me"
        assert "github" in await toolkit.list_named_links()
        assert "Removed" in await toolkit.remove_named_link("github")
        assert "No named link" in await toolkit.get_named_link("github")

    @pytest.mark.asyncio
    async def test_invalid_url_returns_error(self, toolkit: LinkToolkit) -> None:
        result = await toolkit.save_named_link("x", "not-a-url")
        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_store_co_located_with_memory(self, toolkit: LinkToolkit) -> None:
        await toolkit.save_named_link("github", "https://github.com/me")
        expected = toolkit._memory.storage_dir / "named_links.json"  # type: ignore[union-attr]
        assert expected.exists()

    def test_named_tools_registered(self, toolkit: LinkToolkit) -> None:
        names = {t.name for t in toolkit.get_tools()}
        assert {
            "save_named_link",
            "get_named_link",
            "list_named_links",
            "remove_named_link",
        } <= names
