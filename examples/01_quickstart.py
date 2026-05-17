"""Quickstart — simplest possible Hive agent.

Run: uv run python examples/01_quickstart.py
"""

import asyncio

from hive import Agent, Task
from hive.models.anthropic import Anthropic


async def main() -> None:
    provider = Anthropic.lite()

    agent = Agent(
        name="assistant",
        model=provider,
        system_prompt="You are a helpful assistant. Be concise.",
    )

    result = await agent.run(Task(instruction="What are the 3 laws of robotics?"))
    print(f"Status: {result.status}")
    print(f"Output:\n{result.output}")


if __name__ == "__main__":
    asyncio.run(main())
