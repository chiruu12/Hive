"""NDJSON protocol types for Claude Code CLI communication.

Claude Code streams NDJSON via stdout when invoked with --output-format stream-json.
User messages are sent as plain text via stdin in print mode (-p).
"""

import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ContentBlock:
    """A single content block within an assistant message."""

    block_type: str
    text: str | None = None
    thinking: str | None = None
    tool_name: str | None = None
    tool_use_id: str | None = None
    tool_input: dict | None = None


@dataclass
class SystemInit:
    """Initial system message with session metadata."""

    session_id: str
    model: str | None = None
    tools: list[str] = field(default_factory=list)


@dataclass
class AssistantMessage:
    """Claude's response with text and/or tool use blocks."""

    content: list[ContentBlock] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(
            block.text for block in self.content if block.text and block.block_type == "text"
        )

    @property
    def thinking(self) -> str:
        return "".join(
            block.thinking
            for block in self.content
            if block.thinking and block.block_type == "thinking"
        )

    @property
    def tool_uses(self) -> list[ContentBlock]:
        return [block for block in self.content if block.block_type == "tool_use"]


@dataclass
class StreamEvent:
    """Token-level streaming event."""

    event_type: str
    text: str | None = None
    thinking: str | None = None
    tool_name: str | None = None
    tool_input: dict | None = None


@dataclass
class ResultMessage:
    """Final message indicating the turn is complete."""

    session_id: str
    subtype: str = "success"
    cost_usd: float | None = None
    duration_ms: int | None = None
    num_turns: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


InboundMessage = SystemInit | AssistantMessage | StreamEvent | ResultMessage


def parse_ndjson_line(line: str) -> InboundMessage | None:
    """Parse a single NDJSON line from Claude CLI stdout."""
    line = line.strip()
    if not line:
        return None

    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        logger.warning("Failed to parse NDJSON line: %s", line[:200])
        return None

    msg_type = data.get("type")

    if msg_type == "system":
        return SystemInit(
            session_id=data.get("session_id", ""),
            model=data.get("model"),
            tools=data.get("tools", []),
        )

    if msg_type == "assistant":
        content_blocks = []
        message_data = data.get("message", data)
        for block in message_data.get("content", []):
            content_blocks.append(
                ContentBlock(
                    block_type=block.get("type", "text"),
                    text=block.get("text"),
                    thinking=block.get("thinking"),
                    tool_name=block.get("name"),
                    tool_use_id=block.get("id"),
                    tool_input=block.get("input"),
                )
            )
        return AssistantMessage(content=content_blocks)

    if msg_type == "result":
        usage = data.get("usage", {})
        return ResultMessage(
            session_id=data.get("session_id", ""),
            subtype=data.get("subtype", "success"),
            cost_usd=data.get("cost_usd"),
            duration_ms=data.get("duration_ms"),
            num_turns=data.get("num_turns"),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )

    if msg_type in ("content_block_delta", "stream_event"):
        event = data.get("event", data)
        delta = event.get("delta", {})
        return StreamEvent(
            event_type=data.get("event_type", msg_type),
            text=delta.get("text"),
            thinking=delta.get("thinking"),
        )

    return None
