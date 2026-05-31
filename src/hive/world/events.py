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
    # Feedback into the suffering system (D1). Optional; default None leaves
    # existing events unchanged. ``stressor`` names a stressor this choice causes
    # (any string -- SufferingState tolerates unregistered names); ``resolves_stressor``
    # names one it relieves.
    stressor: str | None = None
    stressor_severity: float | None = None
    resolves_stressor: str | None = None


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
    stressor_added: str | None = None
    stressor_resolved: str | None = None
