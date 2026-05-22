"""ChromaDB memory backend — vector search via chromadb and sentence-transformers.

Requires optional dependencies: pip install hive-agent[chromadb]
"""

from __future__ import annotations

import asyncio
import functools
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from hive.memory.semantic import MemoryRecord

logger = logging.getLogger(__name__)


class ChromaBackend:
    """Memory backend using ChromaDB for vector similarity search.

    Use the async factory to create: ``backend = await ChromaBackend.create()``

    All blocking I/O (embedding inference, ChromaDB HTTP calls) is offloaded
    to a thread via run_in_executor to avoid blocking the event loop.

    Requires: chromadb, sentence-transformers
    Install: pip install hive-agent[chromadb]
    """

    def __init__(self, client: Any, collection: Any, embedder: Any, agent_id: str = ""):
        self._agent_id = agent_id
        self._client = client
        self._collection = collection
        self._embedder = embedder

    @classmethod
    async def create(
        cls,
        collection_name: str = "hive_notes",
        agent_id: str = "",
        chroma_url: str = "http://localhost:8000",
        embedding_model: str = "all-MiniLM-L6-v2",
    ) -> ChromaBackend:
        """Async factory — offloads model loading and HTTP calls to a thread."""
        try:
            import chromadb
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ImportError(
                "ChromaBackend requires chromadb and sentence-transformers. "
                "Install with: pip install hive-agent[chromadb]"
            ) from e

        from urllib.parse import urlparse

        parsed = urlparse(chroma_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 8000

        loop = asyncio.get_running_loop()

        def _init() -> tuple[Any, Any, Any]:
            client = chromadb.HttpClient(host=host, port=port)
            collection = client.get_or_create_collection(collection_name)
            embedder = SentenceTransformer(embedding_model)
            return client, collection, embedder

        client, collection, embedder = await loop.run_in_executor(None, _init)
        return cls(client, collection, embedder, agent_id)

    async def _run_sync(self, fn: Any, *args: Any) -> Any:
        """Offload a blocking call to a thread."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, functools.partial(fn, *args))

    async def store(self, text: str, metadata: dict[str, Any] | None = None) -> str:
        mid = f"mem-{uuid4().hex[:8]}"
        meta = dict(metadata) if metadata else {}
        meta["agent_id"] = self._agent_id
        meta["created_at"] = datetime.now(UTC).isoformat()

        embedding = await self._run_sync(self._embedder.encode, text)

        def _add() -> None:
            self._collection.add(
                ids=[mid],
                embeddings=[embedding.tolist()],
                documents=[text],
                metadatas=[meta],
            )

        await self._run_sync(_add)
        return mid

    async def search(self, query: str, top_k: int = 5) -> list[MemoryRecord]:
        embedding = await self._run_sync(self._embedder.encode, query)
        where = {"agent_id": self._agent_id} if self._agent_id else None

        def _query() -> Any:
            return self._collection.query(
                query_embeddings=[embedding.tolist()],
                n_results=top_k,
                where=where,
            )

        results = await self._run_sync(_query)

        records = []
        if results["ids"] and results["ids"][0]:
            for i, mid in enumerate(results["ids"][0]):
                doc = results["documents"][0][i] if results["documents"] else ""
                meta = dict(results["metadatas"][0][i]) if results["metadatas"] else {}
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

        def _get() -> Any:
            return self._collection.get(where=where)

        results = await self._run_sync(_get)

        records = []
        if results["ids"]:
            for i, mid in enumerate(results["ids"]):
                doc = results["documents"][i] if results["documents"] else ""
                meta = dict(results["metadatas"][i]) if results["metadatas"] else {}
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
        try:
            asyncio.get_running_loop()
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                r: list[MemoryRecord] = pool.submit(asyncio.run, self.recent(limit)).result()
                return r
        except RuntimeError:
            r2: list[MemoryRecord] = asyncio.run(self.recent(limit))
            return r2

    async def delete(self, memory_id: str) -> None:
        await self._run_sync(self._collection.delete, [memory_id])

    def count(self) -> int:
        return self._collection.count()  # type: ignore[no-any-return]
