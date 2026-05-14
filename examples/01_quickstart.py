"""Quickstart — simplest possible Hive agent.

Run: uv run python examples/01_quickstart.py
"""

import asyncio

from hive import Agent, Task, create_runtime_provider


async def main() -> None:
    provider = create_runtime_provider("claude-haiku-4-5")

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
