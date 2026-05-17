"""Memory & Comms — agents that remember things and message each other.

Shows MemoryToolkit (persistent key-value store) and CommsToolkit
(inter-agent messaging). Both auto-bind to the agent — no setup needed.

Run: uv run python examples/14_memory_and_comms.py
"""

import asyncio
from pathlib import Path

from hive import Agent, Instructions, Task
from hive.models.anthropic import Anthropic
from hive.tools.comms import CommsToolkit
from hive.tools.memory import MemoryToolkit


async def main() -> None:
    workspace = Path("/tmp/hive-examples/memory-comms")
    workspace.mkdir(parents=True, exist_ok=True)

    provider = Anthropic.lite()
    memory_dir = workspace / "memory"
    comms_dir = workspace / "comms"

    # --- Agent 1: researcher stores findings in memory ---
    researcher = Agent(
        name="researcher",
        model=provider,
        instructions=Instructions(
            persona="a research assistant",
            instructions=[
                "Store important facts in memory using memory_set",
                "When asked to share, send findings to other agents",
            ],
        ),
        toolkits=[
            MemoryToolkit(path=memory_dir),
            CommsToolkit(path=comms_dir),
        ],
        max_steps=10,
    )

    print("=== Researcher stores facts ===\n")
    result = await researcher.run(
        Task(
            instruction=(
                "Store these facts in your memory:\n"
                "- python_creator = 'Guido van Rossum'\n"
                "- python_year = '1991'\n"
                "- python_typing = 'dynamically typed'\n"
                "Then send a message to 'writer' saying the research is done."
            )
        )
    )
    print(f"Researcher: {result.output[:200]}\n")

    # --- Agent 2: writer reads inbox and uses same memory ---
    writer = Agent(
        name="writer",
        model=provider,
        instructions=Instructions(
            persona="a technical writer",
            instructions=[
                "Check your inbox for messages",
                "Use memory_get to retrieve facts",
                "Write a summary based on what you find",
            ],
        ),
        toolkits=[
            MemoryToolkit(path=memory_dir),
            CommsToolkit(path=comms_dir),
        ],
        max_steps=10,
    )

    print("=== Writer reads inbox + memory ===\n")
    result = await writer.run(
        Task(
            instruction=(
                "Check your inbox for messages. Then look up 'python_creator', "
                "'python_year', and 'python_typing' from memory. "
                "Write a one-paragraph summary about Python."
            )
        )
    )
    print(f"Writer: {result.output[:300]}")


if __name__ == "__main__":
    asyncio.run(main())
