"""Core types for the Hive agent runtime."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """Result of executing a tool."""

    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class Message:
    """A single message in a conversation. Provider-agnostic."""

    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str = ""
    name: str = ""

    @staticmethod
    def system(content: str) -> Message:
        return Message(role=Role.SYSTEM, content=content)

    @staticmethod
    def user(content: str) -> Message:
        return Message(role=Role.USER, content=content)

    @staticmethod
    def assistant(content: str, tool_calls: list[ToolCall] | None = None) -> Message:
        tc = tuple(tool_calls) if tool_calls else ()
        return Message(role=Role.ASSISTANT, content=content, tool_calls=tc)

    @staticmethod
    def tool_result(
        tool_call_id: str,
        content: str,
        *,
        is_error: bool = False,
        name: str = "",
    ) -> Message:
        return Message(
            role=Role.TOOL,
            content=content,
            tool_call_id=tool_call_id,
            name=name,
        )


@dataclass(frozen=True)
class GenerateResult:
    """Result from a provider call, carrying the message plus metadata."""

    message: Message
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    duration_ms: int | None = None


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    MAX_STEPS = "max_steps"


class Task(BaseModel):
    """A unit of work for an agent."""

    instruction: str
    id: str = Field(default_factory=lambda: f"task-{uuid.uuid4().hex[:8]}")
    context: dict[str, Any] = {}
    max_steps: int = 25


class TaskResult(BaseModel):
    """Outcome of an agent executing a task."""

    task_id: str
    status: TaskStatus
    output: str = ""
    steps_taken: int = 0
    tool_calls_made: int = 0
    error: str | None = None
    duration_seconds: float = 0.0


class StructuredTaskResult(TaskResult, Generic[T]):
    """TaskResult with a parsed structured output."""

    parsed: T
