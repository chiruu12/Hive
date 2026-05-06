"""Life events — random events with branching choices and consequences."""

from pydantic import BaseModel


class StatEffect(BaseModel):
    stat: str
    change: float
    change_type: str = "absolute"


class ConditionalFollowUp(BaseModel):
    event_id: str
    probability: float
    delay_cycles: int = 1


class Choice(BaseModel):
    id: str
    description: str
    stat_effects: list[StatEffect] = []
    follow_up_events: list[ConditionalFollowUp] = []


class LifeEvent(BaseModel):
    event_id: str
    name: str
    description: str
    category: str
    choices: list[Choice]
    min_cycles_alive: int = 0
    prerequisites: dict[str, float] = {}


class EventOutcome(BaseModel):
    agent_id: str
    event_id: str
    event_name: str = ""
    choice_id: str
    choice_description: str = ""
    stat_changes: dict[str, float] = {}
    follow_ups_triggered: list[str] = []
    cycle: int = 0
