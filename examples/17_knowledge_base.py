"""Knowledge Base — agent that stores and searches notes.

Demonstrates the KnowledgeToolkit with TF-IDF semantic search.

Run: uv run python examples/17_knowledge_base.py
"""

import asyncio
from pathlib import Path

from hive import Agent, Instructions, Task
from hive.memory.semantic import SemanticMemory
from hive.models.anthropic import Anthropic
from hive.tools.knowledge import KnowledgeToolkit


async def main() -> None:
    hive_dir = Path("/tmp/hive-examples/knowledge-demo")
    hive_dir.mkdir(parents=True, exist_ok=True)

    memory = SemanticMemory(hive_dir, "researcher")

    agent = Agent(
        name="researcher",
        model=Anthropic.lite(),
        instructions=Instructions(
            persona="a researcher who saves and retrieves knowledge",
            instructions=[
                "Save important facts as notes with relevant tags",
                "Search before saving to avoid duplicates",
                "Use tags like 'python', 'web', 'database' for categorization",
            ],
        ),
        toolkits=[KnowledgeToolkit(memory)],
        max_steps=15,
    )

    result = await agent.run(
        Task(
            instruction=(
                "Build a small knowledge base about web development:\n"
                "1. Save 3-4 notes about different web technologies "
                "(REST, GraphQL, WebSockets, etc.) with tags\n"
                "2. Search for notes about 'API design'\n"
                "3. List all recent notes"
            )
        )
    )

    print(f"\nStatus: {result.status}")
    print(f"Steps: {result.steps_taken}, Tool calls: {result.tool_calls_made}")
    print(f"\nOutput:\n{result.output}")


if __name__ == "__main__":
    asyncio.run(main())
