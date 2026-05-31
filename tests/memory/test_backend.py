"""Tests for memory backend abstraction."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from hive.memory.semantic import MemoryRecord, SemanticMemory
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

    @pytest.mark.asyncio
    async def test_update_text(self, backend):
        mid = await backend.store("Original text")
        ok = await backend.update(mid, text="Updated text")
        assert ok is True
        rec = await backend.recall(mid)
        assert rec is not None
        assert rec.thought == "Updated text"

    @pytest.mark.asyncio
    async def test_update_metadata(self, backend):
        mid = await backend.store("Note", {"tags": "old"})
        ok = await backend.update(mid, metadata={"tags": "new"})
        assert ok is True
        rec = await backend.recall(mid)
        assert rec is not None
        assert rec.metadata["tags"] == "new"

    @pytest.mark.asyncio
    async def test_update_preserves_timestamp(self, backend):
        mid = await backend.store("Note")
        rec_before = await backend.recall(mid)
        assert rec_before is not None
        await backend.update(mid, text="Changed")
        rec_after = await backend.recall(mid)
        assert rec_after is not None
        assert rec_after.ts == rec_before.ts

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, backend):
        ok = await backend.update("mem-nonexistent", text="nope")
        assert ok is False

    @pytest.mark.asyncio
    async def test_update_no_fields(self, backend):
        mid = await backend.store("Untouched")
        ok = await backend.update(mid)
        assert ok is True
        rec = await backend.recall(mid)
        assert rec is not None
        assert rec.thought == "Untouched"


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


class TestCrossProcessReads:
    """Reads must reflect on-disk appends from another process (no restart)."""

    def _jsonl_path(self, tmp_path: Path) -> Path:
        return tmp_path / "memory" / "test-agent" / "memories.jsonl"

    def _external_line(self, agent_id: str, thought: str) -> str:
        # Simulate a different process appending a note to the same file.
        rec = MemoryRecord(memory_id=f"mem-{thought[:4]}", agent_id=agent_id, thought=thought)
        return rec.model_dump_json() + "\n"

    @pytest.mark.asyncio
    async def test_recent_sees_out_of_band_append(self, tmp_path: Path) -> None:
        backend = TFIDFBackend(tmp_path, "test-agent")
        await backend.store("first note")
        assert backend.count() == 1

        # Out-of-band append by "another process" -- same backend instance, no reload call.
        with open(self._jsonl_path(tmp_path), "a") as f:
            f.write(self._external_line("test-agent", "external note added elsewhere"))

        recent = backend.recent_sync(10)
        thoughts = {r.thought for r in recent}
        assert "external note added elsewhere" in thoughts  # visible without reconstruction
        assert backend.count() == 2

    @pytest.mark.asyncio
    async def test_search_and_async_recent_see_external_append(self, tmp_path: Path) -> None:
        backend = TFIDFBackend(tmp_path, "test-agent")
        await backend.store("agent wrote this")
        with open(self._jsonl_path(tmp_path), "a") as f:
            f.write(self._external_line("test-agent", "pineapple harvest schedule"))

        assert any(r.thought == "pineapple harvest schedule" for r in await backend.recent(10))
        results = await backend.search("pineapple harvest")
        assert any(r.thought == "pineapple harvest schedule" for r in results)

    @pytest.mark.asyncio
    async def test_same_process_writes_still_visible(self, tmp_path: Path) -> None:
        """No regression: a note stored by this backend is immediately visible."""
        backend = TFIDFBackend(tmp_path, "test-agent")
        await backend.store("my own note")
        assert backend.count() == 1
        assert any(r.thought == "my own note" for r in backend.recent_sync(5))

    @pytest.mark.asyncio
    async def test_tolerates_partial_last_line(self, tmp_path: Path) -> None:
        backend = TFIDFBackend(tmp_path, "test-agent")
        await backend.store("complete note")
        # A concurrent appender mid-write leaves a truncated JSON line.
        with open(self._jsonl_path(tmp_path), "a") as f:
            f.write('{"memory_id": "mem-partial", "agent_id": "test-agent", "thoug')

        recent = backend.recent_sync(10)  # must not raise
        thoughts = {r.thought for r in recent}
        assert "complete note" in thoughts
        assert backend.count() == 1  # the partial line is skipped
