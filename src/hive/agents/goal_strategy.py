"""Goal strategy protocol — pluggable goal generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from hive.agents.profile import AgentProfile
    from hive.agents.suffering import SufferingState
    from hive.runtime.persona import Persona
    from hive.world.stats import AgentStats


@dataclass
class GeneratedGoal:
    """Result of a goal-generation call — always carries spend metadata."""

    objective: str | None
    cost_usd: float = 0.0
    tokens: int = 0


@dataclass
class GoalContext:
    agent_id: str
    profile: AgentProfile
    persona: Persona | None
    suffering: SufferingState
    peer_summaries: list[str]
    nudges: list[str]
    recent_goals: list[dict[str, Any]]
    tools_description: str = ""
    world_status: str = ""
    notepad_content: str = ""
    economy_enabled: bool = True
    agent_stats: AgentStats | None = None
    # Relevant semantic-memory snippets for goal generation (daemon-filled).
    memory_snippets: list[str] = field(default_factory=list)
    # When True, daemon skips ExistenceLoop-style validation before saving.
    skip_validation: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class GoalStrategy(Protocol):
    async def generate_goal(self, context: GoalContext) -> GeneratedGoal: ...
