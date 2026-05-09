"""Preset configurations for common interaction types."""

from hive.interactions.base import ChannelType, ExchangeConfig


def agent_chat(rounds: int = 3, topic: str = "") -> ExchangeConfig:
    """Two agents having a conversation."""
    return ExchangeConfig(
        pattern="round_table",
        memory_strategy="full",
        num_rounds=rounds,
        channel_type=ChannelType.DIRECT,
        topic=topic,
    )


def group_discussion(rounds: int = 4, topic: str = "") -> ExchangeConfig:
    """N agents discuss a topic together."""
    return ExchangeConfig(
        pattern="round_table",
        memory_strategy="selective",
        num_rounds=rounds,
        channel_type=ChannelType.GROUP,
        topic=topic,
    )


def interview(rounds: int = 5, topic: str = "") -> ExchangeConfig:
    """One participant asks questions, another answers."""
    return ExchangeConfig(
        pattern="pairs",
        memory_strategy="full",
        num_rounds=rounds,
        channel_type=ChannelType.DIRECT,
        topic=topic,
    )


def debate(rounds: int = 4, topic: str = "") -> ExchangeConfig:
    """Participants take opposing sides on a topic."""
    return ExchangeConfig(
        pattern="round_table",
        memory_strategy="full",
        num_rounds=rounds,
        channel_type=ChannelType.GROUP,
        topic=topic,
        context=f"You are in a debate about: {topic}. Argue your position firmly.",
    )
