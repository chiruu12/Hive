"""Multi-Agent Delegation — a lead agent delegates to specialists.

The lead agent decides what needs doing and delegates subtasks
to a coder and a reviewer. Each runs their own ReAct loop.

Run: uv run python examples/04_multi_agent.py
"""

import asyncio
from pathlib import Path

from hive import Agent, Task
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
        system_prompt=(
            "You are a Python developer. Write clean, tested code. "
            "Use the file and shell tools to create and run files."
        ),
        toolkits=[FileToolkit(workspace), ShellToolkit(workspace)],
        max_steps=10,
    )

    reviewer = Agent(
        name="reviewer",
        model=provider,
        system_prompt=(
            "You are a code reviewer. Read the code files and provide "
            "feedback on quality, bugs, and improvements."
        ),
        toolkits=[FileToolkit(workspace)],
        max_steps=5,
    )

    lead = Agent(
        name="lead",
        model=provider,
        system_prompt=(
            "You are a tech lead. Break tasks into subtasks and delegate "
            "to your team. You have a coder and a reviewer available."
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
