"""Communication tools — agent messaging and shared logging via context."""

import json
from datetime import UTC, datetime

from hive.execution.context import ExecutionContext
from hive.execution.protocol import ToolResult, tool


@tool("agent_message", description="Send message to another agent", target="id", message="text")
async def agent_message(
    agent_id: str,
    context: ExecutionContext | None = None,
    target: str = "",
    message: str = "",
) -> ToolResult:
    """Send a message to another agent's inbox."""
    if not context:
        return ToolResult(success=False, output="No context", error="no_context")
    if not target or not message:
        return ToolResult(success=False, output="Missing target or message", error="missing_params")
    inbox = context.comms_dir / f"{target}_inbox.jsonl"
    entry = json.dumps(
        {
            "from": agent_id,
            "message": message,
            "ts": datetime.now(UTC).isoformat(),
        }
    )
    with open(inbox, "a") as f:
        f.write(entry + "\n")
    return ToolResult(success=True, output=f"Sent to {target}")


@tool("shared_log", description="Write to the shared activity log", entry="log entry text")
async def shared_log(
    agent_id: str, context: ExecutionContext | None = None, entry: str = ""
) -> ToolResult:
    """Append to the shared hive activity log visible to all agents."""
    if not context:
        return ToolResult(success=False, output="No context", error="no_context")
    if not entry:
        return ToolResult(success=False, output="Empty entry", error="empty")
    log_path = context.comms_dir / "shared_log.jsonl"
    record = json.dumps(
        {
            "agent": agent_id,
            "entry": entry,
            "ts": datetime.now(UTC).isoformat(),
        }
    )
    with open(log_path, "a") as f:
        f.write(record + "\n")
    return ToolResult(success=True, output="Logged")
