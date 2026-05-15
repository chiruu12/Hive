"""Multi-Provider — use different models for different tasks.

Shows how to:
1. Use tier presets (.lite(), .standard(), .pro()) for each provider
2. Compare model outputs across providers
3. Use cheap models for simple tasks, powerful models for complex ones

Run: uv run python examples/10_multi_provider.py

Requires at least one API key set. Skips unavailable providers.
"""

import asyncio

from hive import Agent
from hive.models.anthropic import Anthropic
from hive.models.base import BaseProvider
from hive.models.fireworks import Fireworks
from hive.models.groq import Groq
from hive.models.openai import OpenAI

# Each provider has tier presets: .lite(), .standard(), .pro()
PROVIDERS: list[tuple[str, callable]] = [
    ("Anthropic (lite)", Anthropic.lite),
    ("OpenAI (lite)", OpenAI.lite),
    ("Groq (lite)", Groq.lite),
    ("Fireworks (lite)", Fireworks.lite),
]


async def compare_models(prompt: str) -> None:
    """Run the same prompt across all available providers."""
    print(f"Prompt: {prompt}\n")
    print("-" * 60)

    for label, factory in PROVIDERS:
        try:
            provider: BaseProvider = factory()
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
    """Use tier presets for different cost/capability tiers."""
    print("=== Tiered Agent Strategy ===\n")

    try:
        lite = Anthropic.lite()
    except Exception:
        print("Need at least ANTHROPIC_API_KEY for this demo.")
        return

    if not lite.available:
        print("Need at least ANTHROPIC_API_KEY for this demo.")
        return

    # Use .lite() for fast/cheap triage
    triage_agent = Agent(
        name="triage",
        model=lite,
        system_prompt=(
            "Classify the user's request as 'simple' or 'complex'. Reply with just the word."
        ),
    )

    simple_agent = Agent(
        name="simple-handler",
        model=lite,
        system_prompt="You are a fast assistant for simple questions. Be brief.",
    )

    # For complex tasks, you would use Anthropic.standard() or Anthropic.pro()
    # complex_agent = Agent(name="complex-handler", model=Anthropic.standard(), ...)

    questions = [
        "What is 2 + 2?",
        "Explain the tradeoffs between microservices and monoliths for a startup.",
    ]

    for q in questions:
        classification = await triage_agent.run_once(q)
        is_complex = "complex" in classification.lower()

        if is_complex:
            print(f"Q: {q}")
            print("  Routed to: complex handler (would use Anthropic.standard())")
            result = await simple_agent.run_once(q)
        else:
            print(f"Q: {q}")
            print("  Routed to: simple handler (Anthropic.lite())")
            result = await simple_agent.run_once(q)

        print(f"  Answer: {result.strip()[:200]}\n")


async def main() -> None:
    print("=== Model Comparison ===\n")
    await compare_models("What are the three laws of thermodynamics?")

    await tiered_agents()


if __name__ == "__main__":
    asyncio.run(main())
