"""Web Research — agent that fetches pages and searches the internet.

The agent uses WebToolkit to look things up and synthesize answers.

Run: uv run python examples/12_web_research.py
"""

import asyncio

from hive import Agent, Instructions, Task
from hive.models.anthropic import Anthropic
from hive.tools.notepad import NotepadToolkit, Preset
from hive.tools.web import WebToolkit


async def main() -> None:
    agent = Agent(
        name="researcher",
        model=Anthropic.lite(),
        instructions=Instructions(
            persona="a research analyst",
            instructions=[
                "Search the web for information",
                "Read relevant pages for details",
                "Write a summary of your findings to your notepad",
                "Cite your sources",
            ],
        ),
        toolkits=[
            WebToolkit(max_requests_per_cycle=5),
            NotepadToolkit(preset=Preset.journal()),
        ],
        max_steps=15,
    )

    result = await agent.run(
        Task(
            instruction=(
                "Research the current state of WebAssembly (WASM). "
                "What are its main use cases in 2025? "
                "Search the web, read a couple of pages, and write "
                "a brief summary to your notepad."
            )
        )
    )

    print(f"Status: {result.status}")
    print(f"Steps: {result.steps_taken}, Tool calls: {result.tool_calls_made}")
    print(f"\nOutput:\n{result.output}")


if __name__ == "__main__":
    asyncio.run(main())
