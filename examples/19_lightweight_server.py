"""Lightweight Server Pattern — agents as API handlers.

Shows how to use Hive toolkits standalone (no daemon) for server/API usage.
Toolkits are created once at startup, agents created per request.

Run: uv run python examples/19_lightweight_server.py
"""

import asyncio
from pathlib import Path

from hive import Agent, AlarmChecker, AlarmToolkit, KnowledgeToolkit, Persona, TaskToolkit
from hive.models.anthropic import Anthropic

DB_PATH = Path("/tmp/hive-examples/server-demo/app.db")
MEMORY_DIR = Path("/tmp/hive-examples/server-demo/knowledge")


async def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # --- Startup: create reusable toolkits ---
    task_tk = TaskToolkit(db_path=DB_PATH)
    alarm_tk = AlarmToolkit(db_path=DB_PATH)
    knowledge_tk = KnowledgeToolkit(memory_dir=MEMORY_DIR)

    # Bind to a default agent (rebind per-request in production)
    for tk in (task_tk, alarm_tk, knowledge_tk):
        tk.bind("assistant")

    # --- Start alarm checker (background loop) ---
    checker = AlarmChecker(db_path=DB_PATH, check_interval=15)
    alarm_task = asyncio.create_task(checker.run_forever())

    # --- Simulate requests ---
    print("=== Request 1: Create tasks ===")
    agent = Agent(
        name="assistant",
        model=Anthropic.lite(),
        persona=Persona(
            name="Assistant",
            purpose="Help with tasks, notes, and reminders",
        ),
        toolkits=[task_tk, alarm_tk, knowledge_tk],
    )
    result = await agent.run_once(
        "Create three tasks for building a Python CLI app: "
        "1) set up project structure (high priority), "
        "2) implement argument parsing (medium), "
        "3) add --help output (low)",
        max_tool_rounds=10,
    )
    print(result)

    print("\n=== Request 2: Save knowledge ===")
    agent2 = Agent(
        name="assistant",
        model=Anthropic.lite(),
        persona=Persona(name="Researcher", purpose="Save useful information"),
        toolkits=[knowledge_tk],
    )
    result2 = await agent2.run_once(
        "Save these notes: "
        "1) Typer is great for CLI apps, tag it 'python,cli'. "
        "2) Rich makes terminal output beautiful, tag it 'python,tui'.",
        max_tool_rounds=5,
    )
    print(result2)

    print("\n=== Request 3: Set alarm ===")
    agent3 = Agent(
        name="assistant",
        model=Anthropic.lite(),
        persona=Persona(name="Reminder", purpose="Set helpful reminders"),
        toolkits=[alarm_tk],
    )
    result3 = await agent3.run_once(
        "Set an alarm for 5 minutes to review the CLI project progress",
        max_tool_rounds=3,
    )
    print(result3)

    # --- Shutdown ---
    await checker.stop()
    alarm_task.cancel()
    print("\n=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())
