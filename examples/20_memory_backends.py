"""Memory Backends — pluggable storage for semantic memory.

Shows how to use TFIDFBackend (default) and swap in custom backends.

Run: uv run python examples/20_memory_backends.py
"""

import asyncio
from pathlib import Path

from hive.memory.semantic import SemanticMemory
from hive.memory.tfidf_backend import TFIDFBackend


async def main() -> None:
    tmp = Path("/tmp/hive-examples/backends-demo")
    tmp.mkdir(parents=True, exist_ok=True)

    # --- Default: TFIDFBackend is used automatically ---
    print("=== Default SemanticMemory (TFIDFBackend) ===")
    mem = SemanticMemory(tmp, "agent-1")

    await mem.store("Python was created by Guido van Rossum", {"tags": "python,history"})
    await mem.store("Rust guarantees memory safety without GC", {"tags": "rust,safety"})
    await mem.store("Python 3.12 added type parameter syntax", {"tags": "python,types"})
    await mem.store("Go uses goroutines for concurrency", {"tags": "go,concurrency"})

    results = await mem.search("Python type system")
    print(f"Search 'Python type system' ({len(results)} results):")
    for r in results:
        print(f"  - {r.thought} [{r.metadata.get('tags', '')}]")

    print(f"\nRecent notes ({mem.count()} total):")
    for n in mem.recent(3):
        print(f"  - {n.thought[:60]}")

    # --- Explicit backend: same API, explicit construction ---
    print("\n=== Explicit TFIDFBackend ===")
    backend = TFIDFBackend(tmp / "custom-store", "researcher")
    mem2 = SemanticMemory(tmp / "custom-store", "researcher", backend=backend)

    await mem2.store("Neural networks learn representations from data")
    await mem2.store("Transformers use self-attention mechanisms")
    await mem2.store("GPT models are autoregressive language models")

    results2 = await mem2.search("attention mechanism")
    print(f"Search 'attention mechanism': {len(results2)} result(s)")
    for r in results2:
        print(f"  - {r.thought}")

    # --- ChromaDB backend (requires: pip install hive-agent[chromadb]) ---
    print("\n=== ChromaDB Backend (optional) ===")
    try:
        from hive.memory.chroma_backend import ChromaBackend  # noqa: F401

        print("  chromadb + sentence-transformers available")
        print("  Usage: ChromaBackend(collection_name='notes', agent_id='my-agent')")
        print("  Then: SemanticMemory(hive_dir, agent_id, backend=chroma_backend)")
    except ImportError:
        print("  Not installed. Run: pip install hive-agent[chromadb]")

    print("\n=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())
