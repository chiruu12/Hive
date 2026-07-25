"""Shared helpers for semantic memory recall in prompts."""

from __future__ import annotations

import logging

from hive.memory.semantic import SemanticMemory

logger = logging.getLogger(__name__)


async def recall_snippets(
    memory: SemanticMemory,
    query: str,
    *,
    limit: int = 3,
) -> list[str]:
    """Return up to *limit* thought strings relevant to *query*."""
    query = query.strip()
    if not query:
        return []
    try:
        records = await memory.search(query, top_k=limit)
        return [r.thought for r in records if r.thought]
    except Exception:
        logger.debug("Memory recall failed for query %r", query[:80], exc_info=True)
        return []
