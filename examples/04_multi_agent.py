"""Multi-Agent Delegation — a lead agent delegates to specialists.

The lead agent decides what needs doing and delegates subtasks
to a coder and a reviewer. Each runs their own ReAct loop.

Run: uv run python examples/04_multi_agent.py
"""

import asyncio
from pathlib import Path

from hive import Agent, Instructions, Task
from hive.models.anthropic import Anthropic
from hive.tools.delegation import DelegationToolkit
from hive.tools.file import FileToolkit
from hive.tools.shell import ShellToolkit


async def main() -> None:
    workspace = Path("/tmp/hive-examples/multi-agent")
    workspace.mkdir(parents=True, exist_ok=True)

    provider = Anthropic.lite()

    coder = Agent(
        name="coder",
        model=provider,
        instructions=Instructions(
            persona="a Python developer",
            instructions=["Write clean, tested code", "Run code to verify"],
        ),
        toolkits=[FileToolkit(workspace=workspace), ShellToolkit(workspace=workspace)],
        max_steps=10,
    )

    reviewer = Agent(
        name="reviewer",
        model=provider,
        instructions=Instructions(
            persona="a code reviewer",
            instructions=["Read code and provide feedback on quality and bugs"],
        ),
        toolkits=[FileToolkit(workspace=workspace)],
        max_steps=5,
    )

    lead = Agent(
        name="lead",
        model=provider,
        instructions=Instructions(
            persona="a tech lead",
            instructions=[
                "Break tasks into subtasks",
                "Delegate coding to the coder",
                "Delegate reviews to the reviewer",
            ],
        ),
        toolkits=[DelegationToolkit({"coder": coder, "reviewer": reviewer})],
        max_steps=10,
    )

    result = await lead.run(
        Task(
            instruction=(
                "Create a Python function that checks if a string is a palindrome. "
                "First delegate the coding to the coder, then delegate a review "
                "to the reviewer."
            )
        )
    )

    print(f"\nStatus: {result.status}")
    print(f"Steps: {result.steps_taken}, Tool calls: {result.tool_calls_made}")
    print(f"\nLead's summary:\n{result.output}")


if __name__ == "__main__":
    asyncio.run(main())
