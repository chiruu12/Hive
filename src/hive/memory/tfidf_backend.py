"""TF-IDF memory backend — file-based JSONL storage with cosine similarity search."""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from hive.memory.semantic import MemoryRecord


class TFIDFBackend:
    """Default memory backend using JSONL file storage and TF-IDF search."""

    def __init__(self, storage_dir: Path, agent_id: str):
        self._agent_id = agent_id
        self._dir = storage_dir / "memory" / agent_id
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "memories.jsonl"
        self._records: dict[str, MemoryRecord] = {}
        self._load()
        # (mtime, size) of the JSONL as last loaded. Used to detect out-of-band
        # writes from other processes and reload the index without a restart.
        self._stat = self._current_stat()

    def _current_stat(self) -> tuple[float, int] | None:
        try:
            st = self._path.stat()
        except OSError:
            return None
        return (st.st_mtime, st.st_size)

    def _load(self) -> None:
        if not self._path.exists():
            return
        for line in self._path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = MemoryRecord.model_validate_json(line)
            except Exception:
                # Tolerate a partial/half-written last line from a concurrent
                # appender; it will parse on the next reload once fully flushed.
                continue
            self._records[rec.memory_id] = rec

    def _reload_if_changed(self) -> None:
        """Reload the index if the JSONL changed on disk (another process appended).

        One cheap stat() per read; reloads only when (mtime, size) differs from
        the last load. In-process writes refresh the cached stat (see _append /
        _save), so they never trigger a redundant reload.
        """
        current = self._current_stat()
        if current == self._stat:
            return
        self._records = {}
        self._load()
        self._stat = current

    def _save(self) -> None:
        lines = [r.model_dump_json() for r in self._records.values()]
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + "\n" if lines else "")
        tmp.rename(self._path)
        self._stat = self._current_stat()

    def _append(self, rec: MemoryRecord) -> None:
        with open(self._path, "a") as f:
            f.write(rec.model_dump_json() + "\n")
        self._stat = self._current_stat()

    async def store(self, text: str, metadata: dict[str, Any] | None = None) -> str:
        mid = f"mem-{uuid4().hex[:8]}"
        rec = MemoryRecord(
            memory_id=mid,
            agent_id=self._agent_id,
            thought=text,
            metadata=metadata or {},
        )
        self._records[mid] = rec
        self._append(rec)
        return mid

    async def search(self, query: str, top_k: int = 5) -> list[MemoryRecord]:
        self._reload_if_changed()
        if not self._records:
            return []
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        idf = _compute_idf([_tokenize(_record_text(r)) for r in self._records.values()])
        query_vec = _tfidf_vector(query_tokens, idf)

        scored = []
        for rec in self._records.values():
            doc_vec = _tfidf_vector(_tokenize(_record_text(rec)), idf)
            sim = _cosine_similarity(query_vec, doc_vec)
            if sim > 0.05:
                scored.append((sim, rec))

        scored.sort(key=lambda x: x[0], reverse=True)

        now = datetime.now(UTC)
        results = []
        for _, rec in scored[:top_k]:
            rec.access_count += 1
            rec.last_accessed = now
            results.append(rec)

        if results:
            self._save()
        return results

    async def recent(self, limit: int = 5) -> list[MemoryRecord]:
        self._reload_if_changed()
        recs = sorted(self._records.values(), key=lambda r: r.ts, reverse=True)
        return recs[:limit]

    def recent_sync(self, limit: int = 5) -> list[MemoryRecord]:
        self._reload_if_changed()
        recs = sorted(self._records.values(), key=lambda r: r.ts, reverse=True)
        return recs[:limit]

    async def delete(self, memory_id: str) -> None:
        # Reload first: _save() rewrites the whole file from self._records, so
        # without this an external append since the last read would be lost.
        self._reload_if_changed()
        if memory_id in self._records:
            del self._records[memory_id]
            self._save()

    def count(self) -> int:
        self._reload_if_changed()
        return len(self._records)

    async def recall(self, memory_id: str) -> MemoryRecord | None:
        self._reload_if_changed()
        rec = self._records.get(memory_id)
        if rec:
            rec.access_count += 1
            rec.last_accessed = datetime.now(UTC)
            self._save()
        return rec

    async def update(
        self,
        memory_id: str,
        text: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        # Reload first so a full-file _save() preserves external appends.
        self._reload_if_changed()
        rec = self._records.get(memory_id)
        if rec is None:
            return False
        changed = False
        if text is not None:
            rec.thought = text
            changed = True
        if metadata is not None:
            rec.metadata = metadata
            changed = True
        if changed:
            self._save()
        return True

    async def consolidate(self, max_age_days: int = 30, min_access: int = 2) -> int:
        # Reload first so a full-file _save() preserves external appends.
        self._reload_if_changed()
        now = datetime.now(UTC)
        to_remove = []
        for mid, rec in self._records.items():
            age = (now - rec.ts).days
            if age > max_age_days and rec.access_count < min_access:
                to_remove.append(mid)
        for mid in to_remove:
            del self._records[mid]
        if to_remove:
            self._save()
        return len(to_remove)


_STOP_WORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "shall",
    "can",
    "to",
    "of",
    "in",
    "for",
    "on",
    "with",
    "at",
    "by",
    "from",
    "as",
    "into",
    "through",
    "during",
    "before",
    "after",
    "and",
    "but",
    "or",
    "nor",
    "not",
    "so",
    "yet",
    "both",
    "either",
    "neither",
    "each",
    "every",
    "all",
    "any",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "no",
    "only",
    "own",
    "same",
    "than",
    "too",
    "very",
    "just",
    "because",
    "about",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "i",
    "me",
    "my",
    "we",
    "our",
    "you",
    "your",
    "he",
    "him",
    "his",
    "she",
    "her",
    "they",
    "them",
}


def _tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if w not in _STOP_WORDS and len(w) > 1]


def _record_text(rec: MemoryRecord) -> str:
    """Extract searchable text from a record: thought + metadata string values."""
    parts = [rec.thought]
    for v in rec.metadata.values():
        if isinstance(v, str) and v:
            parts.append(v)
    return " ".join(parts)


def _compute_idf(docs: list[list[str]]) -> dict[str, float]:
    n = len(docs)
    if n == 0:
        return {}
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(set(doc))
    return {term: math.log((n + 1) / (count + 1)) + 1 for term, count in df.items()}


def _tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    tf: Counter[str] = Counter(tokens)
    total = len(tokens) if tokens else 1
    return {t: (c / total) * idf.get(t, 1.0) for t, c in tf.items()}


def _cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) & set(b)
    if not keys:
        return 0.0
    dot = sum(a[k] * b[k] for k in keys)
    mag_a = math.sqrt(sum(v * v for v in a.values()))
    mag_b = math.sqrt(sum(v * v for v in b.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)
