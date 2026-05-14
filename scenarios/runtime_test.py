"""Quick test of the new runtime Agent with real API calls."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from hive.config import load_config
from hive.runtime import (
    Agent,
    Task,
    Toolkit,
    create_runtime_provider,
    tool,
)


class MathToolkit(Toolkit):
    """Simple math tools for testing the ReAct loop."""

    @tool()
    def add(self, a: int, b: int) -> str:
        """Add two numbers together.

        Args:
            a: First number.
            b: Second number.
        """
        return str(int(a) + int(b))

    @tool()
    def multiply(self, a: int, b: int) -> str:
        """Multiply two numbers together.

        Args:
            a: First number.
            b: Second number.
        """
        return str(int(a) * int(b))


async def test_model(model_name: str, label: str) -> dict:
    """Test one model with the ReAct loop."""
    print(f"\n{'='*60}")
    print(f"  Testing: {label}")
    print(f"  Model:   {model_name}")
    print(f"{'='*60}")

    try:
        provider = create_runtime_provider(model_name)
    except Exception as e:
        print(f"  SKIP: Could not create provider: {e}")
        return {"model": label, "status": "skip", "error": str(e)}

    agent = Agent(
        name=f"test-{label}",
        model=provider,
        system_prompt=(
            "You are a helpful math assistant. Use the provided tools "
            "to solve problems. Always use tools for calculations — "
            "never compute in your head."
        ),
        toolkits=[MathToolkit()],
        max_steps=10,
    )

    task = Task(
        instruction=(
            "What is (15 + 27) multiplied by 3? "
            "Use the add tool first, then the multiply tool. "
            "Report the final answer."
        ),
        max_steps=10,
    )

    print(f"  Task: {task.instruction}")
    print("  Running...")

    result = await agent.run(task)

    print(f"  Status: {result.status}")
    print(f"  Steps: {result.steps_taken}")
    print(f"  Tool calls: {result.tool_calls_made}")
    print(f"  Duration: {result.duration_seconds:.2f}s")
    print(f"  Output: {result.output[:300]}")

    correct = "126" in result.output
    print(f"  Expected 126: {'CORRECT' if correct else 'WRONG'}")

    if result.error:
        print(f"  Error: {result.error}")

    return {
        "model": label,
        "status": str(result.status),
        "steps": result.steps_taken,
        "tool_calls": result.tool_calls_made,
        "duration": round(result.duration_seconds, 2),
        "correct": correct,
        "error": result.error,
    }


async def main():
    load_config(Path.cwd() / ".hive" if (Path.cwd() / ".hive").exists() else None)

    from hive.config import get_env

    models = [
        ("claude-haiku-4-5", "Claude Haiku 4.5"),
    ]

    if get_env("FIREWORKS_API_KEY"):
        models.extend([
            ("accounts/fireworks/models/kimi-k2p6", "Kimi K2P6"),
            ("accounts/fireworks/models/minimax-m2p7", "MiniMax M2P7"),
            ("accounts/fireworks/models/deepseek-v3p2", "DeepSeek V3P2"),
            ("accounts/fireworks/models/gpt-oss-120b", "GPT-OSS 120B"),
        ])

    print("\n" + "=" * 60)
    print("  HIVE RUNTIME AGENT TEST")
    print("  Testing ReAct loop with real API calls")
    print("=" * 60)

    results = []
    for model_name, label in models:
        r = await test_model(model_name, label)
        results.append(r)

    print(f"\n{'='*60}")
    print("  SCORECARD")
    print(f"{'='*60}")
    print(f"  {'Model':<20s} {'Status':<12s} {'Tools':<7s} {'Time':<8s} {'Answer'}")
    print(f"  {'-'*20} {'-'*12} {'-'*7} {'-'*8} {'-'*7}")
    for r in results:
        answer = "CORRECT" if r.get("correct") else "WRONG"
        if r["status"] == "skip":
            answer = "SKIP"
        print(
            f"  {r['model']:<20s} {r['status']:<12s} "
            f"{r.get('tool_calls', '-'):<7} "
            f"{str(r.get('duration', '-')) + 's':<8s} "
            f"{answer}"
        )
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
