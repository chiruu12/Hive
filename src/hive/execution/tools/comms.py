"""Communication tools — agent messaging and shared logging."""

import json
from datetime import UTC, datetime
from pathlib import Path

from hive.execution.protocol import ToolResult, tool

_COMMS_DIR: Path | None = None


def set_comms_dir(hive_dir: Path) -> None:
    global _COMMS_DIR
    _COMMS_DIR = hive_dir / "comms"
    _COMMS_DIR.mkdir(parents=True, exist_ok=True)


@tool("agent_message", description="Send message to another agent", target="id", message="text")
async def agent_message(agent_id: str, target: str = "", message: str = "") -> ToolResult:
    """Send a message to another agent's inbox."""
    if not target or not message:
        return ToolResult(success=False, output="Missing target or message", error="missing_params")
    if _COMMS_DIR is None:
        return ToolResult(success=False, output="Comms not initialized", error="no_comms_dir")
    inbox = _COMMS_DIR / f"{target}_inbox.jsonl"
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
async def shared_log(agent_id: str, entry: str = "") -> ToolResult:
    """Append to the shared hive activity log visible to all agents."""
    if not entry:
        return ToolResult(success=False, output="Empty entry", error="empty")
    if _COMMS_DIR is None:
        return ToolResult(success=False, output="Comms not initialized", error="no_comms_dir")
    log_path = _COMMS_DIR / "shared_log.jsonl"
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
