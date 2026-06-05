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
    is_error: bool = False

    @staticmethod
    def system(content: str) -> Message:
        """Create a new Message with system role."""
        return Message(role=Role.SYSTEM, content=content)

    @staticmethod
    def user(content: str) -> Message:
        """Create a new Message with user role."""
        return Message(role=Role.USER, content=content)

    @staticmethod
    def assistant(content: str, tool_calls: list[ToolCall] | None = None) -> Message:
        """Create a new Message with assistant role."""
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
        """Create a new Message with tool result role."""
        return Message(
            role=Role.TOOL,
            content=content,
            tool_call_id=tool_call_id,
            name=name,
            is_error=is_error,
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


class StreamEventType(StrEnum):
    TEXT = "text"
    DONE = "done"


@dataclass(frozen=True)
class StreamEvent:
    """One event from a streaming generation.

    ``TEXT`` events carry an incremental ``text`` delta; the terminal ``DONE``
    event carries the full aggregated ``result`` (message, tool calls, usage).
    """

    type: StreamEventType
    text: str = ""
    result: GenerateResult | None = None


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    MAX_STEPS = "max_steps"
    WAITING_APPROVAL = "waiting_approval"


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
    cost_usd: float = 0.0
    total_tokens: int = 0


class StructuredTaskResult(TaskResult, Generic[T]):
    """TaskResult with a parsed structured output.

    ``parsed`` is ``None`` when ``status`` is ``FAILED`` (generation or parsing
    failed); it is a validated instance on ``COMPLETED``.
    """

    parsed: T | None = None
