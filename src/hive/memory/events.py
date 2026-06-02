"""Event log - JSONL append-only session recording."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class EventType(StrEnum):
    AGENT_SPAWNED = "agent_spawned"
    TASK_STARTED = "task_started"
    TOOL_USED = "tool_used"
    TOOL_RESULT = "tool_result"
    ASSISTANT_MESSAGE = "assistant_message"
    TASK_COMPLETED = "task_completed"
    ERROR = "error"
    GOAL_SET = "goal_set"
    GOAL_COMPLETED = "goal_completed"
    GOAL_ABANDONED = "goal_abandoned"
    SUFFERING_CHANGED = "suffering_changed"
    NUDGE_RECEIVED = "nudge_received"
    EXISTENCE_CYCLE = "existence_cycle"
    DAEMON_CYCLE = "daemon_cycle"
    JOURNAL_ENTRY = "journal_entry"


class HiveEvent(BaseModel):
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_type: EventType
    agent_id: str
    session_id: str
    data: dict[str, Any] = {}

    def to_jsonl(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_jsonl(cls, line: str) -> "HiveEvent":
        return cls.model_validate_json(line)


class EventLog:
    """Append-only JSONL event stream for agent sessions.

    Each session is one file opened only in append mode ("a"); events are never
    rewritten or removed in place, so the log is append-only by construction.

    With ``fsync=True`` every append is flushed and ``os.fsync``'d before
    returning, so a power/OS crash cannot lose an acknowledged event. This costs
    one fsync per event, so it defaults to off (it runs off the event loop via a
    worker thread, but the syscall is still on the per-event write path).
    """

    def __init__(self, hive_dir: Path, fsync: bool = False):
        self._sessions_dir = hive_dir / "sessions"
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        self._fsync = fsync

    def _session_path(self, agent_id: str, session_id: str) -> Path:
        agent_dir = self._sessions_dir / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        return agent_dir / f"{session_id}.jsonl"

    async def append(self, event: HiveEvent) -> None:
        path = self._session_path(event.agent_id, event.session_id)
        line = event.to_jsonl() + "\n"
        await asyncio.to_thread(self._write_line, path, line)

    def _write_line(self, path: Path, line: str) -> None:
        is_new = not path.exists()
        with open(path, "a") as f:
            f.write(line)
            if self._fsync:
                f.flush()
                os.fsync(f.fileno())
        if self._fsync and is_new:
            # fsync the parent dir so a freshly-created file's directory entry
            # is durably linked (content fsync alone doesn't guarantee this).
            try:
                dir_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass  # some platforms/filesystems don't support directory fsync

    async def replay(self, agent_id: str, session_id: str) -> list[HiveEvent]:
        path = self._session_path(agent_id, session_id)
        if not path.exists():
            return []
        text = await asyncio.to_thread(path.read_text)
        if not text:
            return []
        # A complete append always ends in "\n"; if the file doesn't, the final
        # line is a torn/half-written record we tolerate. Earlier lines (and a
        # final line on a newline-terminated file) must parse -- a failure there
        # is real corruption and is surfaced, not silently dropped.
        ends_clean = text.endswith("\n")
        # Split ONLY on "\n" -- str.splitlines() also breaks on \r, \v, \f, NEL
        # and Unicode  / , which are legal (unescaped) inside JSON
        # strings, so a single record carrying one in its text would be shredded.
        lines = text.split("\n")
        if ends_clean and lines and lines[-1] == "":
            lines = lines[:-1]  # drop the empty element after a trailing newline
        events = []
        for idx, raw in enumerate(lines):
            line = raw.rstrip("\r")  # tolerate CRLF
            if not line.strip():
                continue
            try:
                events.append(HiveEvent.from_jsonl(line))
            except ValueError:
                # pydantic ValidationError / JSON errors subclass ValueError.
                if idx == len(lines) - 1 and not ends_clean:
                    continue  # torn final write -- expected, skip it
                raise
        return events

    async def stream(self, agent_id: str) -> AsyncIterator[HiveEvent]:
        """Tail-follow the latest session file for an agent."""
        agent_dir = self._sessions_dir / agent_id
        if not agent_dir.exists():
            return

        sessions = sorted(agent_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        if not sessions:
            return

        path = sessions[-1]
        offset = 0

        while True:
            text = await asyncio.to_thread(path.read_text)
            chunk = text[offset:]
            # Only consume up to the last newline; a trailing partial line (an
            # in-progress append) is left for the next poll once fully flushed.
            nl = chunk.rfind("\n")
            if nl != -1:
                complete = chunk[: nl + 1]
                # Split only on "\n" (see replay): splitlines() would shred a
                # record containing a Unicode line separator in its text.
                for raw in complete.split("\n"):
                    line = raw.rstrip("\r")
                    if not line.strip():
                        continue
                    # These are complete (newline-terminated) lines, so a parse
                    # error is real corruption -- let it surface rather than
                    # silently dropping events.
                    yield HiveEvent.from_jsonl(line)
                offset += len(complete)
            await asyncio.sleep(0.3)

    async def list_sessions(self, agent_id: str) -> list[str]:
        agent_dir = self._sessions_dir / agent_id
        if not agent_dir.exists():
            return []
        return [p.stem for p in agent_dir.glob("*.jsonl")]


def stream_agent_events(agent_name: str) -> None:
    """Sync entry point for CLI `hive logs` command."""
    from rich.console import Console

    console = Console()
    hive_dir = Path.cwd() / ".hive"

    if not hive_dir.exists():
        console.print("[red]No .hive directory found. Run `hive init` first.[/red]")
        return

    event_log = EventLog(hive_dir)

    async def _stream() -> None:
        async for event in event_log.stream(agent_name):
            _print_event(console, event)

    try:
        asyncio.run(_stream())
    except KeyboardInterrupt:
        pass


def replay_session(session_id: str) -> None:
    """Sync entry point for CLI `hive replay` command."""
    from rich.console import Console

    console = Console()
    hive_dir = Path.cwd() / ".hive"

    if not hive_dir.exists():
        console.print("[red]No .hive directory found. Run `hive init` first.[/red]")
        return

    event_log = EventLog(hive_dir)

    async def _replay() -> None:
        sessions_dir = hive_dir / "sessions"
        for agent_dir in sessions_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            session_path = agent_dir / f"{session_id}.jsonl"
            if session_path.exists():
                events = await event_log.replay(agent_dir.name, session_id)
                for event in events:
                    _print_event(console, event, detailed=True)
                return
        console.print(f"[red]Session {session_id} not found.[/red]")

    asyncio.run(_replay())


def _print_event(console: Any, event: HiveEvent, detailed: bool = False) -> None:
    """Pretty-print a single event to console."""
    color_map = {
        EventType.AGENT_SPAWNED: "green",
        EventType.TASK_STARTED: "blue",
        EventType.TOOL_USED: "cyan",
        EventType.TOOL_RESULT: "dim",
        EventType.ASSISTANT_MESSAGE: "white",
        EventType.TASK_COMPLETED: "green",
        EventType.ERROR: "red",
    }

    color = color_map.get(event.event_type, "white")
    ts_str = event.ts.strftime("%H:%M:%S")

    if event.event_type == EventType.TOOL_USED:
        tool = event.data.get("tool", "?")
        console.print(f"  [{color}]{ts_str} ⚡ {tool}[/{color}]")
        if detailed and "params" in event.data:
            params = json.dumps(event.data["params"], indent=2)[:200]
            console.print(f"    [dim]{params}[/dim]")

    elif event.event_type == EventType.ASSISTANT_MESSAGE:
        text = event.data.get("text", "")[:200]
        console.print(f"  [{color}]{ts_str} 💬 {text}[/{color}]")

    elif event.event_type == EventType.TASK_COMPLETED:
        tokens = event.data.get("input_tokens", 0) + event.data.get("output_tokens", 0)
        duration = event.data.get("duration_ms", 0)
        console.print(f"  [{color}]{ts_str} ✓ Completed ({tokens} tokens, {duration}ms)[/{color}]")

    elif event.event_type == EventType.ERROR:
        msg = event.data.get("message", "Unknown error")
        console.print(f"  [{color}]{ts_str} ✗ {msg}[/{color}]")

    else:
        label = event.event_type.value.replace("_", " ").title()
        console.print(f"  [{color}]{ts_str} {label}[/{color}]")
