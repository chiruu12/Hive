"""Tests for memory backend abstraction."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from hive.memory.semantic import SemanticMemory
from hive.memory.tfidf_backend import TFIDFBackend


class TestTFIDFBackend:
    @pytest.fixture
    def backend(self, tmp_path: Path) -> TFIDFBackend:
        return TFIDFBackend(tmp_path, "test-agent")

    @pytest.mark.asyncio
    async def test_store_and_search(self, backend):
        await backend.store("Python is a programming language", {"tags": "python"})
        await backend.store("JavaScript runs in browsers", {"tags": "js"})
        await backend.store("Python supports list comprehensions", {"tags": "python"})

        results = await backend.search("Python programming")
        assert len(results) > 0
        assert "Python" in results[0].thought

    @pytest.mark.asyncio
    async def test_store_returns_id(self, backend):
        mid = await backend.store("test note")
        assert mid.startswith("mem-")

    @pytest.mark.asyncio
    async def test_recent(self, backend):
        await backend.store("First")
        await backend.store("Second")
        await backend.store("Third")

        recent = await backend.recent(2)
        assert len(recent) == 2

    def test_recent_sync(self, backend):
        import asyncio

        asyncio.run(backend.store("Note 1"))
        asyncio.run(backend.store("Note 2"))

        recent = backend.recent_sync(2)
        assert len(recent) == 2

    @pytest.mark.asyncio
    async def test_delete(self, backend):
        mid = await backend.store("Delete me")
        assert backend.count() == 1

        await backend.delete(mid)
        assert backend.count() == 0

    @pytest.mark.asyncio
    async def test_recall(self, backend):
        mid = await backend.store("Important fact")
        rec = await backend.recall(mid)
        assert rec is not None
        assert rec.access_count == 1

    @pytest.mark.asyncio
    async def test_consolidate(self, backend):
        mid = await backend.store("Old note")
        backend._records[mid].ts = backend._records[mid].ts.replace(year=2020)
        backend._save()

        removed = await backend.consolidate(max_age_days=1, min_access=1)
        assert removed == 1
        assert backend.count() == 0

    @pytest.mark.asyncio
    async def test_persistence(self, tmp_path):
        b1 = TFIDFBackend(tmp_path, "agent")
        await b1.store("Persisted note")

        b2 = TFIDFBackend(tmp_path, "agent")
        assert b2.count() == 1
        results = await b2.search("Persisted")
        assert len(results) == 1

    def test_count_empty(self, backend):
        assert backend.count() == 0


class TestSemanticMemoryWithBackend:
    @pytest.mark.asyncio
    async def test_default_backend_is_tfidf(self, tmp_path):
        mem = SemanticMemory(tmp_path, "agent")
        assert isinstance(mem._backend, TFIDFBackend)

    @pytest.mark.asyncio
    async def test_custom_backend(self, tmp_path):
        custom = TFIDFBackend(tmp_path, "custom-agent")
        mem = SemanticMemory(tmp_path, "agent", backend=custom)
        assert mem._backend is custom

    @pytest.mark.asyncio
    async def test_store_delegates(self, tmp_path):
        mem = SemanticMemory(tmp_path, "agent")
        mid = await mem.store("Test thought", {"key": "value"})
        assert mid.startswith("mem-")
        assert mem.count() == 1

    @pytest.mark.asyncio
    async def test_search_delegates(self, tmp_path):
        mem = SemanticMemory(tmp_path, "agent")
        await mem.store("Python programming language")
        await mem.store("Java enterprise framework")

        results = await mem.search("Python")
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_forget_delegates_to_delete(self, tmp_path):
        mem = SemanticMemory(tmp_path, "agent")
        mid = await mem.store("Forget me")
        await mem.forget(mid)
        assert mem.count() == 0

    def test_recent_sync(self, tmp_path):
        import asyncio

        mem = SemanticMemory(tmp_path, "agent")
        asyncio.run(mem.store("Note"))
        recent = mem.recent(5)
        assert len(recent) == 1


class TestChromaBackendImport:
    @pytest.mark.asyncio
    async def test_import_error_without_deps(self):
        with patch.dict("sys.modules", {"chromadb": None, "sentence_transformers": None}):
            from hive.memory.chroma_backend import ChromaBackend

            with pytest.raises(ImportError, match="chromadb"):
                await ChromaBackend.create()
