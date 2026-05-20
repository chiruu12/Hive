"""Goal strategy protocol — pluggable goal generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from hive.agents.profile import AgentProfile
    from hive.agents.suffering import SufferingState
    from hive.runtime.persona import Persona


@dataclass
class Goal:
    goal_id: str
    objective: str
    reasoning: str | None = None


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
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class GoalStrategy(Protocol):
    async def generate_goal(self, context: GoalContext) -> Goal | None: ...
