"""Multi-Agent Collaboration — agents discuss and debate using ExchangeRunner.

Shows how to use the interaction system for structured multi-agent
conversations: round-table discussions, paired debates, and freeform chats.

Run: uv run python examples/24_multi_agent_collaboration.py
"""

import asyncio

from hive.interactions.base import ExchangeConfig
from hive.interactions.exchange import ExchangeRunner
from hive.interactions.participants import AgentParticipant, EnvironmentParticipant
from hive.models.anthropic import Anthropic


async def main() -> None:
    provider = Anthropic.lite()

    # Create agent participants with distinct personas
    philosopher = AgentParticipant(
        participant_id="philosopher",
        name="Philosopher",
        model=provider,
        persona="a deep thinker who considers ethical implications",
    )

    engineer = AgentParticipant(
        participant_id="engineer",
        name="Engineer",
        model=provider,
        persona="a pragmatic engineer focused on feasibility and trade-offs",
    )

    # An environment participant that provides context
    moderator = EnvironmentParticipant(
        participant_id="moderator",
        name="Moderator",
        response_fn=lambda msgs: (
            "Please discuss the topic thoroughly. "
            "Consider both ethical and practical aspects."
            if len(msgs) <= 2
            else "Interesting points. Can you address the counterarguments?"
        ),
    )

    # Run a round-table discussion
    print("=== Round-Table Discussion ===\n")
    config = ExchangeConfig(
        pattern="round_table",
        num_rounds=3,
        topic=(
            "Should AI systems be allowed to make"
            " autonomous decisions about resource allocation?"
        ),
        context="A debate about AI autonomy in critical infrastructure",
    )
    runner = ExchangeRunner(config)
    result = await runner.run([philosopher, engineer, moderator])

    print(f"Exchange ID: {result.exchange_id}")
    print(f"Rounds completed: {result.rounds_completed}")
    print(f"Total messages: {len(result.messages)}\n")

    for msg in result.messages:
        print(f"[Round {msg.round}] {msg.sender_name}: {msg.content}\n")

    # Run a paired debate
    print("\n=== Paired Debate ===\n")
    config_pairs = ExchangeConfig(
        pattern="pairs",
        num_rounds=2,
        topic="Is open-source AI safer than proprietary AI?",
    )
    runner_pairs = ExchangeRunner(config_pairs)
    result_pairs = await runner_pairs.run([philosopher, engineer])

    for msg in result_pairs.messages:
        print(f"[Round {msg.round}] {msg.sender_name} -> {msg.recipient_id}: {msg.content}\n")

    print(f"Total messages: {len(result_pairs.messages)}")


if __name__ == "__main__":
    asyncio.run(main())
