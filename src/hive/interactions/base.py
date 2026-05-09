"""Base classes for multi-agent interaction scenarios."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Participant-based interaction system (new)
# ---------------------------------------------------------------------------


class ChannelType(StrEnum):
    DIRECT = "direct"
    GROUP = "group"
    BROADCAST = "broadcast"


@runtime_checkable
class Participant(Protocol):
    """Anything that can participate in an interaction."""

    @property
    def participant_id(self) -> str: ...

    @property
    def name(self) -> str: ...

    async def respond(
        self,
        messages: list[InteractionMessage],
        context: str = "",
        system_prompt: str = "",
    ) -> str: ...


@dataclass(frozen=True)
class InteractionMessage:
    """A message within an interaction session."""

    round: int
    sender_id: str
    sender_name: str
    content: str
    recipient_id: str = "all"
    visible_to: tuple[str, ...] = ()
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExchangeConfig:
    """Configuration for an Exchange session."""

    pattern: str = "round_table"
    memory_strategy: str = "full"
    num_rounds: int = 4
    max_tokens_per_turn: int = 300
    channel_type: ChannelType = ChannelType.GROUP
    topic: str = ""
    context: str = ""


@dataclass
class ExchangeResult:
    """Result of a completed exchange."""

    exchange_id: str = field(default_factory=lambda: f"ex-{uuid4().hex[:8]}")
    messages: list[InteractionMessage] = field(default_factory=list)
    rounds_completed: int = 0
    participant_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Legacy scenario system (kept for backward compatibility)
# ---------------------------------------------------------------------------


class AgentSlot(BaseModel):
    """An agent participating in a scenario."""

    slot_id: str
    name: str
    model: str
    persona: str = ""
    role: str = ""
    secret: str = ""
    memory_type: str = "selective"
    system_prompt: str = ""


class Message(BaseModel):
    """A single message in the interaction."""

    round: int
    sender: str
    recipient: str = "all"
    content: str
    visible_to: list[str] = []
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = {}
    tokens: int = 0
    cost_usd: float = 0.0


class RoundResult(BaseModel):
    """Result of one round of interaction."""

    round_num: int
    messages: list[Message] = []
    actions: dict[str, Any] = {}
    evidence_revealed: str = ""


class ScenarioResult(BaseModel):
    """Final result of a completed scenario."""

    name: str
    rounds: list[RoundResult] = []
    final_actions: dict[str, Any] = {}
    scores: dict[str, float] = {}
    total_tokens: int = 0
    total_cost: float = 0.0
    winner: str = ""
    transcript_path: str = ""


class InteractionPattern(ABC):
    """How agents communicate with each other."""

    @abstractmethod
    async def run_round(
        self,
        agents: list[AgentSlot],
        round_num: int,
        history: list[RoundResult],
        context_builder: Any,
        provider_factory: Any,
    ) -> RoundResult: ...

    @abstractmethod
    def get_visible_messages(self, agent_id: str, history: list[RoundResult]) -> list[Message]: ...


class MemoryStrategy(ABC):
    """What an agent remembers between rounds."""

    @abstractmethod
    def build_context(
        self,
        agent: AgentSlot,
        visible_messages: list[Message],
        round_num: int,
    ) -> str: ...


class Scenario(ABC):
    """A playable multi-agent scenario."""

    name: str = ""
    pattern_type: str = "round_table"
    num_rounds: int = 4

    @abstractmethod
    def setup(self) -> list[AgentSlot]: ...

    @abstractmethod
    def build_round_prompt(self, agent: AgentSlot, round_num: int, memory_context: str) -> str: ...

    @abstractmethod
    def evaluate(self, result: ScenarioResult) -> dict[str, float]: ...

    def get_evidence(self, round_num: int) -> str:
        return ""

    def get_final_prompt(self, agent: AgentSlot, memory_context: str) -> str:
        return ""
