"""Task Management — agent that creates and organizes tasks.

Demonstrates the TaskToolkit for SQLite-backed task CRUD.

Run: uv run python examples/16_task_management.py
"""

import asyncio
from pathlib import Path

from hive import Agent, Instructions, Task
from hive.memory.store import HiveStore
from hive.models.anthropic import Anthropic
from hive.tools.tasks import TaskToolkit


async def main() -> None:
    hive_dir = Path("/tmp/hive-examples/tasks-demo")
    hive_dir.mkdir(parents=True, exist_ok=True)

    store = HiveStore(hive_dir / "hive.db")
    await store.initialize()

    agent = Agent(
        name="planner",
        model=Anthropic.lite(),
        instructions=Instructions(
            persona="a project planner who breaks work into tasks",
            instructions=[
                "Create tasks with clear descriptions and priorities",
                "Use high priority for blockers, medium for normal, low for nice-to-have",
                "Complete tasks when done, delete if no longer relevant",
            ],
        ),
        toolkits=[TaskToolkit(store)],
        max_steps=15,
    )

    result = await agent.run(
        Task(
            instruction=(
                "Plan a small Python CLI project:\n"
                "1. Create 4-5 tasks for building a todo app CLI\n"
                "2. List all pending tasks\n"
                "3. Complete the first task (assume it's done)\n"
                "4. Show the updated task list"
            )
        )
    )

    print(f"\nStatus: {result.status}")
    print(f"Steps: {result.steps_taken}, Tool calls: {result.tool_calls_made}")
    print(f"\nOutput:\n{result.output}")


if __name__ == "__main__":
    asyncio.run(main())
