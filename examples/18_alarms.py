"""Alarms — agent that sets and manages timed reminders.

Demonstrates the AlarmToolkit with macOS notifications.

Run: uv run python examples/18_alarms.py
"""

import asyncio
from pathlib import Path

from hive import Agent, Instructions, Task
from hive.memory.store import HiveStore
from hive.models.anthropic import Anthropic
from hive.tools.alarms import AlarmToolkit


async def main() -> None:
    hive_dir = Path("/tmp/hive-examples/alarms-demo")
    hive_dir.mkdir(parents=True, exist_ok=True)

    store = HiveStore(hive_dir / "hive.db")
    await store.initialize()

    agent = Agent(
        name="assistant",
        model=Anthropic.lite(),
        instructions=Instructions(
            persona="a personal assistant that manages reminders",
            instructions=[
                "Set alarms with clear descriptions",
                "Confirm each alarm with the scheduled time",
                "Cancel alarms when asked",
            ],
        ),
        toolkits=[AlarmToolkit(store)],
        max_steps=10,
    )

    result = await agent.run(
        Task(
            instruction=(
                "Help me set up reminders for my afternoon:\n"
                "1. Set an alarm for a standup meeting in 1 hour\n"
                "2. Set an alarm for a break in 30 minutes\n"
                "3. List all pending alarms\n"
                "4. Cancel the break alarm"
            )
        )
    )

    print(f"\nStatus: {result.status}")
    print(f"Steps: {result.steps_taken}, Tool calls: {result.tool_calls_made}")
    print(f"\nOutput:\n{result.output}")


if __name__ == "__main__":
    asyncio.run(main())
