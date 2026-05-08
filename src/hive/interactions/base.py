"""Base classes for multi-agent interaction scenarios."""

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


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
