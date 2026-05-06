"""Agent state - runtime state for a living agent."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class AgentStatus(StrEnum):
    """Possible agent states."""

    IDLE = "idle"
    WORKING = "working"
    WAITING = "waiting_approval"
    ERROR = "error"
    DEAD = "dead"


class AgentState(BaseModel):
    """Runtime state of a spawned agent."""

    agent_id: str
    name: str
    role: str
    model: str
    status: AgentStatus = AgentStatus.IDLE
    current_task: str | None = None
    current_goal: str | None = None
    suffering_load: float = 0.0
    goals_completed: int = 0
    steps_completed: int = 0
    steps_total: int = 0
    spawned_at: datetime = Field(default_factory=datetime.now)
    last_active: datetime = Field(default_factory=datetime.now)
    error: str | None = None
    workspace: str = ""

    def is_alive(self) -> bool:
        return self.status != AgentStatus.DEAD

    def is_busy(self) -> bool:
        return self.status in (AgentStatus.WORKING, AgentStatus.WAITING)
