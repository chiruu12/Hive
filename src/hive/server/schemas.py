"""Request/response DTOs for the Hive REST API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SpawnRequest(BaseModel):
    preset: str
    model: str | None = None


class SpawnResponse(BaseModel):
    agent_id: str


class AgentSummary(BaseModel):
    agent_id: str
    name: str
    role: str
    model: str
    status: str
    goal: str | None = None


class NudgeRequest(BaseModel):
    message: str


class TaskRequest(BaseModel):
    instruction: str
    max_steps: int = 25
    # Optional session binding (multi-tenant). When omitted, an anonymous session
    # scoped to the caller's user is created.
    session_id: str | None = None
    session_key: str | None = None


class TaskResponse(BaseModel):
    task_id: str
    status: str
    output: str = ""
    steps_taken: int = 0
    tool_calls_made: int = 0
    session_id: str
    approval_ids: list[str] = Field(default_factory=list)


class ApprovalSummary(BaseModel):
    approval_id: str
    agent_id: str
    tool_name: str
    arguments: str
    status: str
    created_at: str
    session_id: str | None = None
    goal_id: str | None = None
    reason: str | None = None
    resolved_by: str | None = None


class ApprovalDecisionRequest(BaseModel):
    decision: str  # "approve" | "deny"
    reason: str | None = None


class SessionCreateRequest(BaseModel):
    agent_id: str
    task: str = ""
    session_key: str | None = None
    metadata: dict[str, Any] | None = None


class SessionSummary(BaseModel):
    session_id: str
    agent_id: str
    user_id: str | None = None
    session_key: str | None = None
    task: str
    status: str
    started_at: str | None = None
