"""Multi-agent interactions — patterns, participants, and exchanges."""

from hive.interactions.base import (
    AgentSlot,
    ChannelType,
    ExchangeConfig,
    ExchangeResult,
    InteractionMessage,
    InteractionPattern,
    MemoryStrategy,
    Message,
    Participant,
    RoundResult,
    Scenario,
    ScenarioResult,
)
from hive.interactions.exchange import ExchangeRunner
from hive.interactions.participants import (
    AgentParticipant,
    EnvironmentParticipant,
    HumanParticipant,
)
from hive.interactions.presets import agent_chat, debate, group_discussion, interview
from hive.interactions.runner import ScenarioRunner

__all__ = [
    "AgentParticipant",
    "AgentSlot",
    "ChannelType",
    "EnvironmentParticipant",
    "ExchangeConfig",
    "ExchangeResult",
    "ExchangeRunner",
    "HumanParticipant",
    "InteractionMessage",
    "InteractionPattern",
    "MemoryStrategy",
    "Message",
    "Participant",
    "RoundResult",
    "Scenario",
    "ScenarioResult",
    "ScenarioRunner",
    "agent_chat",
    "debate",
    "group_discussion",
    "interview",
]
