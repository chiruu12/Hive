"""Streaming & Capabilities — token streaming and provider introspection.

Shows how to:
1. Introspect a provider with supports() and availability() (no API call)
2. Stream assistant text token-by-token via the on_text callback
3. Run a fully standalone agent (no daemon)

Run: uv run python examples/23_streaming_and_capabilities.py

The introspection section runs without any API key. The streaming run is
skipped if no Anthropic key is configured.
"""

import asyncio
import sys

from hive import Agent, Task
from hive.models.anthropic import Anthropic
from hive.models.base import Availability, Capability


def show_capabilities() -> Anthropic:
    """Inspect what a provider can do and whether it's usable -- offline."""
    provider = Anthropic.lite()

    print("Capabilities:")
    for cap in Capability:
        mark = "yes" if provider.supports(cap) else "no"
        print(f"  {cap.value:18} {mark}")

    status = provider.availability()
    print(f"\nAvailability: {status.value}")
    if status is not Availability.AVAILABLE:
        # NO_API_KEY vs UNREACHABLE lets you give the user a precise reason.
        print("  (set ANTHROPIC_API_KEY to run the streaming demo below)")
    return provider


async def stream_a_reply(provider: Anthropic) -> None:
    """Stream tokens as they arrive using the on_text callback."""
    print("\nStreaming reply:\n")

    def on_text(delta: str) -> None:
        sys.stdout.write(delta)
        sys.stdout.flush()

    agent = Agent(
        name="streamer",
        model=provider,
        system_prompt="You are concise.",
        on_text=on_text,
    )
    result = await agent.run(Task(instruction="In two sentences, what is a hive mind?"))
    print(f"\n\n[done: {result.status.value}, {result.steps_taken} step(s)]")


async def main() -> None:
    provider = show_capabilities()
    if provider.supports(Capability.STREAMING) and provider.available:
        await stream_a_reply(provider)
    else:
        print("\nSkipping streaming run (provider unavailable).")


if __name__ == "__main__":
    asyncio.run(main())
