"""Zero Config — the absolute minimum to get an agent running.

Every toolkit has sensible defaults. No paths, no IDs, no setup.
Just create and go.

Run: uv run python examples/15_zero_config.py
"""

import asyncio

from hive import Agent, Instructions, Task
from hive.models.anthropic import Anthropic
from hive.tools.file import FileToolkit
from hive.tools.git import GitToolkit
from hive.tools.memory import MemoryToolkit
from hive.tools.notepad import NotepadToolkit
from hive.tools.shell import ShellToolkit
from hive.tools.web import WebToolkit


async def main() -> None:
    # Every toolkit works with zero config.
    # Paths default to CWD, agent_id is auto-bound by the Agent.

    agent = Agent(
        name="fullstack",
        model=Anthropic.lite(),
        instructions=Instructions(
            persona="a full-stack developer with access to every tool",
            instructions=[
                "Use the right tool for each task",
                "Keep notes in your notepad",
                "Search the web when you need information",
            ],
        ),
        toolkits=[
            FileToolkit(),  # defaults to CWD
            ShellToolkit(),  # defaults to CWD, restricted mode
            GitToolkit(),  # defaults to CWD
            WebToolkit(),  # 10 requests per cycle
            MemoryToolkit(),  # .hive/agent_memory/
            NotepadToolkit(),  # .hive/journals/, default preset
        ],
    )

    # All toolkits auto-bind to agent_id="fullstack"
    print(f"Agent: {agent}")
    print(f"Tools: {[t.name for t in agent.get_tools()]}")
    print(f"System prompt preview:\n{agent._system_prompt[:300]}...")

    result = await agent.run(
        Task(instruction="What tools do you have available? List them and write a note about it.")
    )
    print(f"\nOutput:\n{result.output[:400]}")


if __name__ == "__main__":
    asyncio.run(main())
