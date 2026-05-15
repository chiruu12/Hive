"""Error Handling & Budget Limits — production patterns.

Demonstrates:
1. Checking TaskResult status and handling failures
2. Budget enforcement (max_cost_usd, max_tokens)
3. Max steps behavior
4. Tool errors that don't crash the agent

Run: uv run python examples/09_error_handling.py
"""

import asyncio

from hive import Agent, Task, TaskStatus, Toolkit, create_runtime_provider, tool


class FlakyToolkit(Toolkit):
    """A toolkit where some tools intentionally fail — for testing error handling."""

    @tool()
    def reliable_tool(self, query: str) -> str:
        """A tool that always works.

        Args:
            query: Any input.
        """
        return f"Result for: {query}"

    @tool()
    def flaky_tool(self, data: str) -> str:
        """A tool that sometimes fails. Use with caution.

        Args:
            data: Input data to process.
        """
        if "fail" in data.lower():
            raise RuntimeError("Connection timeout — service unavailable")
        return f"Processed: {data}"


async def demo_status_handling() -> None:
    """Show how to handle different task outcomes."""
    print("=== 1. Status Handling ===\n")

    provider = create_runtime_provider("claude-haiku-4-5")
    agent = Agent(
        name="worker",
        model=provider,
        system_prompt="You are a helpful assistant. Be concise.",
        toolkits=[FlakyToolkit()],
        max_steps=5,
    )

    result = await agent.run(
        Task(instruction="Use the reliable_tool with query 'hello world', then summarize.")
    )

    match result.status:
        case TaskStatus.COMPLETED:
            print(f"Success: {result.output[:200]}")
        case TaskStatus.FAILED:
            print(f"Failed: {result.error}")
        case TaskStatus.MAX_STEPS:
            print(f"Hit step limit after {result.steps_taken} steps")
            print(f"Partial output: {result.output[:200]}")
        case _:
            print(f"Unexpected status: {result.status}")

    print(f"  Steps: {result.steps_taken}, Tools: {result.tool_calls_made}")
    print(f"  Duration: {result.duration_seconds:.1f}s\n")


async def demo_budget_limit() -> None:
    """Show budget enforcement stopping an agent."""
    print("=== 2. Budget Limit ===\n")

    provider = create_runtime_provider("claude-haiku-4-5")
    agent = Agent(
        name="budget-worker",
        model=provider,
        system_prompt="You are a helpful assistant.",
        max_cost_usd=0.0001,
        max_steps=20,
    )

    result = await agent.run(
        Task(
            instruction=(
                "Write a detailed essay about the history of computing, "
                "covering at least 10 major milestones."
            )
        )
    )

    if result.status == TaskStatus.FAILED and result.error and "budget" in result.error.lower():
        print(f"Budget enforced: {result.error}")
    else:
        print(f"Status: {result.status}")
        print(f"Output: {result.output[:200]}...")

    print(f"  Steps: {result.steps_taken}\n")


async def demo_max_steps() -> None:
    """Show what happens when an agent hits the step limit."""
    print("=== 3. Max Steps ===\n")

    provider = create_runtime_provider("claude-haiku-4-5")
    agent = Agent(
        name="limited-worker",
        model=provider,
        system_prompt="You are a helpful assistant. Use tools for every question.",
        toolkits=[FlakyToolkit()],
        max_steps=2,
    )

    result = await agent.run(
        Task(
            instruction=(
                "Use the reliable_tool three times with queries 'first', "
                "'second', and 'third', then give me a summary."
            )
        )
    )

    print(f"Status: {result.status}")
    if result.status == TaskStatus.MAX_STEPS:
        print("Agent ran out of steps before completing the task.")
    print(f"  Steps taken: {result.steps_taken}/{2}")
    print(f"  Tool calls: {result.tool_calls_made}")
    print(f"  Output: {result.output[:200]}\n")


async def demo_tool_errors() -> None:
    """Show that tool errors don't crash the agent — it adapts."""
    print("=== 4. Tool Error Recovery ===\n")

    provider = create_runtime_provider("claude-haiku-4-5")
    agent = Agent(
        name="resilient-worker",
        model=provider,
        system_prompt=(
            "You are a helpful assistant. If a tool fails, explain the "
            "error and try a different approach."
        ),
        toolkits=[FlakyToolkit()],
        max_steps=10,
    )

    result = await agent.run(
        Task(
            instruction=(
                "First try flaky_tool with data 'this will fail', "
                "then use reliable_tool with 'backup plan'."
            )
        )
    )

    print(f"Status: {result.status}")
    print(f"Steps: {result.steps_taken}, Tools: {result.tool_calls_made}")
    print(f"Output: {result.output[:300]}\n")


async def main() -> None:
    await demo_status_handling()
    await demo_budget_limit()
    await demo_max_steps()
    await demo_tool_errors()


if __name__ == "__main__":
    asyncio.run(main())
