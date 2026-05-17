"""Custom Toolkit — build domain-specific tools for your agents.

Shows how to:
1. Create a Toolkit subclass with @tool-decorated methods
2. Use standalone @tool functions with collect_tools
3. Mix both approaches in one agent

Run: uv run python examples/07_custom_toolkit.py
"""

import asyncio
import json
from datetime import UTC, datetime

from hive import Agent, Task, Toolkit, collect_tools, tool
from hive.models.anthropic import Anthropic

# --- In-memory data store (simulates a database) ---

TASKS_DB: dict[str, dict[str, str]] = {}


# --- Approach 1: Toolkit subclass (recommended for related tools) ---


class ProjectToolkit(Toolkit):
    """Tools for managing a project task board."""

    def __init__(self, project_name: str):
        self._project = project_name

    @tool()
    def create_task(self, title: str, priority: str = "medium") -> str:
        """Create a new task on the project board.

        Args:
            title: Short description of the task.
            priority: One of low, medium, high, critical.
        """
        task_id = f"TASK-{len(TASKS_DB) + 1:03d}"
        TASKS_DB[task_id] = {
            "title": title,
            "priority": priority,
            "status": "todo",
            "project": self._project,
            "created": datetime.now(UTC).isoformat(),
        }
        return json.dumps({"id": task_id, "title": title, "priority": priority})

    @tool()
    def list_tasks(self, status: str = "") -> str:
        """List all tasks, optionally filtered by status.

        Args:
            status: Filter by status (todo, in_progress, done). Empty for all.
        """
        tasks = [
            {"id": tid, **t}
            for tid, t in TASKS_DB.items()
            if t["project"] == self._project and (not status or t["status"] == status)
        ]
        if not tasks:
            return "No tasks found."
        return json.dumps(tasks, indent=2)

    @tool()
    def update_task(self, task_id: str, status: str) -> str:
        """Update the status of a task.

        Args:
            task_id: The task ID (e.g. TASK-001).
            status: New status: todo, in_progress, or done.
        """
        if task_id not in TASKS_DB:
            return f"Error: {task_id} not found."
        TASKS_DB[task_id]["status"] = status
        return f"Updated {task_id} to '{status}'."


# --- Approach 2: Standalone @tool functions (for one-off tools) ---


@tool()
def get_current_time() -> str:
    """Get the current UTC time."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


@tool()
def calculate(expression: str) -> str:
    """Evaluate a mathematical expression safely.

    Args:
        expression: A math expression like '2 + 3 * 4'.
    """
    allowed = set("0123456789+-*/.() ")
    if not all(c in allowed for c in expression):
        return "Error: only numeric expressions allowed."
    try:
        return str(eval(expression))  # noqa: S307
    except Exception as e:
        return f"Error: {e}"


async def main() -> None:
    provider = Anthropic.lite()

    agent = Agent(
        name="project-manager",
        model=provider,
        system_prompt=(
            "You are a project manager. Use the available tools to manage "
            "tasks and answer questions. Be efficient and organized."
        ),
        toolkits=[ProjectToolkit("hive-v2")],
        tools=collect_tools(get_current_time, calculate),
        max_steps=15,
    )

    result = await agent.run(
        Task(
            instruction=(
                "Set up the project board for our next sprint:\n"
                "1. Create a high-priority task for 'Implement user authentication'\n"
                "2. Create a medium-priority task for 'Write API documentation'\n"
                "3. Create a low-priority task for 'Update dependencies'\n"
                "4. List all tasks to confirm they were created\n"
                "5. Mark the documentation task as in_progress\n"
                "6. Give me a summary of the board state"
            )
        )
    )

    print(f"Status: {result.status}")
    print(f"Steps: {result.steps_taken}, Tool calls: {result.tool_calls_made}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    print(f"\nOutput:\n{result.output}")
    print(f"\nFinal DB state: {json.dumps(TASKS_DB, indent=2)}")


if __name__ == "__main__":
    asyncio.run(main())
