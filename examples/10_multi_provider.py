"""Multi-Provider — use different models for different tasks.

Shows how to:
1. Create providers for different backends
2. Use cheap models for simple tasks, powerful models for complex ones
3. Compare model outputs on the same prompt

Run: uv run python examples/10_multi_provider.py

Requires at least one API key set. Skips unavailable providers.
"""

import asyncio

from hive import Agent, create_runtime_provider
from hive.runtime.providers import RuntimeProvider

MODELS = [
    ("claude-haiku-4-5", "Anthropic Claude Haiku"),
    ("gpt-5.4-nano", "OpenAI GPT-5.4 Nano"),
    ("groq:llama-3.3-70b-versatile", "Groq Llama 3.3 70B"),
    ("fireworks:accounts/fireworks/models/deepseek-v4-pro", "Fireworks DeepSeek V4"),
]


async def compare_models(prompt: str) -> None:
    """Run the same prompt across all available providers."""
    print(f"Prompt: {prompt}\n")
    print("-" * 60)

    for model_name, label in MODELS:
        try:
            provider: RuntimeProvider = create_runtime_provider(model_name)
        except Exception:
            print(f"  [{label}] — skipped (provider unavailable)")
            continue

        if not provider.available:
            print(f"  [{label}] — skipped (no API key or server not running)")
            continue

        agent = Agent(
            name="tester",
            model=provider,
            system_prompt="Answer in exactly one sentence. Be precise.",
        )

        try:
            result = await agent.run_once(prompt)
            print(f"\n  [{label}]")
            print(f"  {result.strip()}")
        except Exception as e:
            print(f"\n  [{label}] — error: {e}")

    print()


async def tiered_agents() -> None:
    """Use different models for different cost/capability tiers."""
    print("=== Tiered Agent Strategy ===\n")

    try:
        cheap = create_runtime_provider("claude-haiku-4-5")
    except Exception:
        print("Need at least ANTHROPIC_API_KEY for this demo.")
        return

    if not cheap.available:
        print("Need at least ANTHROPIC_API_KEY for this demo.")
        return

    triage_agent = Agent(
        name="triage",
        model=cheap,
        system_prompt=(
            "Classify the user's request as 'simple' or 'complex'. Reply with just the word."
        ),
    )

    simple_agent = Agent(
        name="simple-handler",
        model=cheap,
        system_prompt="You are a fast assistant for simple questions. Be brief.",
    )

    questions = [
        "What is 2 + 2?",
        "Explain the tradeoffs between microservices and monoliths for a startup.",
    ]

    for q in questions:
        classification = await triage_agent.run_once(q)
        is_complex = "complex" in classification.lower()

        if is_complex:
            print(f"Q: {q}")
            print("  Routed to: complex handler (would use a stronger model)")
            result = await simple_agent.run_once(q)
        else:
            print(f"Q: {q}")
            print("  Routed to: simple handler (cheap model)")
            result = await simple_agent.run_once(q)

        print(f"  Answer: {result.strip()[:200]}\n")


async def main() -> None:
    print("=== Model Comparison ===\n")
    await compare_models("What are the three laws of thermodynamics?")

    await tiered_agents()


if __name__ == "__main__":
    asyncio.run(main())
