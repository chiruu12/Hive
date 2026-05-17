"""Tools — agent with file, shell, and git access.

Creates a workspace, writes code, runs it, and commits with git.

Run: uv run python examples/02_tools.py
"""

import asyncio
from pathlib import Path

from hive import Agent, Instructions, Task
from hive.models.anthropic import Anthropic
from hive.tools.file import FileToolkit
from hive.tools.git import GitToolkit
from hive.tools.shell import ShellToolkit


async def main() -> None:
    workspace = Path("/tmp/hive-examples/tools-demo")
    workspace.mkdir(parents=True, exist_ok=True)

    agent = Agent(
        name="coder",
        model=Anthropic.lite(),
        instructions=Instructions(
            persona="a developer working in an isolated workspace",
            instructions=[
                "Write clean, well-structured code",
                "Run code to verify before committing",
                "Use descriptive commit messages",
            ],
        ),
        toolkits=[
            FileToolkit(workspace=workspace),
            ShellToolkit(workspace=workspace),
            GitToolkit(workspace=workspace),
        ],
        max_steps=15,
    )

    result = await agent.run(
        Task(
            instruction=(
                "1. Initialize a git repo\n"
                "2. Create fibonacci.py that prints the first 10 fibonacci numbers\n"
                "3. Run it to verify the output\n"
                "4. Commit the file with a descriptive message"
            )
        )
    )

    print(f"\nStatus: {result.status}")
    print(f"Steps: {result.steps_taken}, Tool calls: {result.tool_calls_made}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    print(f"\nOutput:\n{result.output}")


if __name__ == "__main__":
    asyncio.run(main())
