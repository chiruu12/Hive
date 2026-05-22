"""ChromaDB memory backend — vector search via chromadb and sentence-transformers.

Requires optional dependencies: pip install hive-agent[chromadb]
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from hive.memory.semantic import MemoryRecord

logger = logging.getLogger(__name__)


class ChromaBackend:
    """Memory backend using ChromaDB for vector similarity search.

    Requires: chromadb, sentence-transformers
    Install: pip install hive-agent[chromadb]
    """

    def __init__(
        self,
        collection_name: str = "hive_notes",
        agent_id: str = "",
        chroma_url: str = "http://localhost:8000",
        embedding_model: str = "all-MiniLM-L6-v2",
    ):
        try:
            import chromadb
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ImportError(
                "ChromaBackend requires chromadb and sentence-transformers. "
                "Install with: pip install hive-agent[chromadb]"
            ) from e

        from urllib.parse import urlparse

        self._agent_id = agent_id
        parsed = urlparse(chroma_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 8000
        self._client = chromadb.HttpClient(host=host, port=port)
        self._collection = self._client.get_or_create_collection(collection_name)
        self._embedder = SentenceTransformer(embedding_model)

    async def store(self, text: str, metadata: dict[str, Any] | None = None) -> str:
        mid = f"mem-{uuid4().hex[:8]}"
        meta = dict(metadata) if metadata else {}
        meta["agent_id"] = self._agent_id
        meta["created_at"] = datetime.now(UTC).isoformat()

        embedding = self._embedder.encode(text).tolist()
        self._collection.add(
            ids=[mid],
            documents=[text],
            embeddings=[embedding],
            metadatas=[meta],
        )
        return mid

    async def search(self, query: str, top_k: int = 5) -> list[MemoryRecord]:
        embedding = self._embedder.encode(query).tolist()
        where = {"agent_id": self._agent_id} if self._agent_id else None
        results = self._collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            where=where,
        )

        records = []
        if results["ids"] and results["ids"][0]:
            for i, mid in enumerate(results["ids"][0]):
                doc = results["documents"][0][i] if results["documents"] else ""
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                created = meta.pop("created_at", datetime.now(UTC).isoformat())
                agent = meta.pop("agent_id", self._agent_id)
                records.append(
                    MemoryRecord(
                        memory_id=mid,
                        agent_id=agent,
                        thought=doc,
                        metadata=meta,
                        ts=datetime.fromisoformat(created),
                    )
                )
        return records

    async def recent(self, limit: int = 5) -> list[MemoryRecord]:
        where = {"agent_id": self._agent_id} if self._agent_id else None
        results = self._collection.get(where=where)

        records = []
        if results["ids"]:
            for i, mid in enumerate(results["ids"]):
                doc = results["documents"][i] if results["documents"] else ""
                meta = results["metadatas"][i] if results["metadatas"] else {}
                created = meta.pop("created_at", datetime.now(UTC).isoformat())
                agent = meta.pop("agent_id", self._agent_id)
                records.append(
                    MemoryRecord(
                        memory_id=mid,
                        agent_id=agent,
                        thought=doc,
                        metadata=meta,
                        ts=datetime.fromisoformat(created),
                    )
                )
        records.sort(key=lambda r: r.ts, reverse=True)
        return records[:limit]

    def recent_sync(self, limit: int = 5) -> list[MemoryRecord]:
        import asyncio

        try:
            asyncio.get_running_loop()
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, self.recent(limit)).result()
        except RuntimeError:
            return asyncio.run(self.recent(limit))

    async def delete(self, memory_id: str) -> None:
        self._collection.delete(ids=[memory_id])

    def count(self) -> int:
        result: int = self._collection.count()
        return result
