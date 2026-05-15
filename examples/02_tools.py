"""Tools — agent with file, shell, and git access.

Creates a workspace, writes code, runs it, and commits with git.

Run: uv run python examples/02_tools.py
"""

import asyncio
from pathlib import Path

from hive import Agent, Task, create_runtime_provider
from hive.runtime import FileToolkit, GitToolkit, ShellToolkit


async def main() -> None:
    workspace = Path("/tmp/hive-examples/tools-demo")
    workspace.mkdir(parents=True, exist_ok=True)

    provider = create_runtime_provider("claude-haiku-4-5")
    agent = Agent(
        name="coder",
        model=provider,
        system_prompt=(
            "You are a developer working in an isolated workspace. "
            "Write clean code, run it to verify, and commit your work."
        ),
        toolkits=[
            FileToolkit(workspace),
            ShellToolkit(workspace),
            GitToolkit(workspace),
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

    fib = workspace / "fibonacci.py"
    if fib.exists():
        print(f"\nFile created ({fib}):\n{fib.read_text()}")


if __name__ == "__main__":
    asyncio.run(main())
