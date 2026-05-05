"""Structured log models for full session capture."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class RunLog(BaseModel):
    run_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    heartbeat: int
    profiles: list[str]
    agents_spawned: list[str] = []
    tools_available: list[str] = []


class CycleLog(BaseModel):
    run_id: str
    cycle: int
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    agents_active: int = 0
    agents_in_crisis: int = 0
    goals_completed_this_cycle: int = 0
    goals_abandoned_this_cycle: int = 0


class GoalLog(BaseModel):
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    agent_id: str
    goal_id: str
    event: str
    objective: str | None = None
    reasoning: str | None = None
    plan: list[dict[str, Any]] | None = None
    outcome_summary: str | None = None
    steps_done: int | None = None
    steps_failed: int | None = None


class DecisionLog(BaseModel):
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    agent_id: str
    decision_type: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    duration_ms: int | None = None
    response_raw: str = ""
    response_parsed: dict[str, Any] | None = None
    success: bool = True


class ToolLog(BaseModel):
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    agent_id: str
    goal_id: str = ""
    step_index: int = 0
    tool_name: str
    params_raw: dict[str, Any] = {}
    params_resolved: dict[str, Any] = {}
    success: bool = False
    output: str = ""
    error: str | None = None
    duration_ms: int = 0
    artifacts: list[str] = []


class SufferingLog(BaseModel):
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    agent_id: str
    cycle: int = 0
    cumulative_load: float = 0.0
    active_stressors: list[dict[str, Any]] = []
    events: list[str] = []
