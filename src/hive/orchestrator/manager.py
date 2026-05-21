"""Session manager — concurrent session pool with history persistence."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from hive.orchestrator.session import (
    ClaudeCodeSession,
    CodexSession,
    SessionResult,
    SessionStatus,
)

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages concurrent code sessions with queuing and persistence."""

    def __init__(
        self,
        hive_dir: Path,
        max_concurrent: int = 3,
    ):
        self._hive_dir = hive_dir
        self._sessions_dir = hive_dir / "sessions" / "orchestrator"
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._sessions: dict[str, ClaudeCodeSession | CodexSession] = {}
        self._results: dict[str, SessionResult] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def create(
        self,
        task: str,
        workspace: str,
        tool: str = "claude",
        model: str = "sonnet",
        timeout: int = 300,
    ) -> str:
        """Create and start a new code session. Returns session_id."""
        if tool == "codex":
            session = CodexSession(
                task=task,
                workspace=workspace,
                model=model,
                timeout=timeout,
            )
        else:
            session = ClaudeCodeSession(
                task=task,
                workspace=workspace,
                model=model,
                timeout=timeout,
            )

        session_id = session.session_id
        self._sessions[session_id] = session
        self._tasks[session_id] = asyncio.create_task(self._run_session(session_id))
        return session_id

    async def _run_session(self, session_id: str) -> None:
        session = self._sessions[session_id]
        async with self._semaphore:
            try:
                result = await session.wait()
                self._results[session_id] = result
                self._persist_result(result)
            except Exception as e:
                logger.error("Session %s failed: %s", session_id, e)
                self._results[session_id] = SessionResult(
                    session_id=session_id,
                    task="",
                    output=f"Error: {e}",
                    exit_code=-1,
                    duration_ms=0,
                    model="",
                    tool="unknown",
                )

    def get_status(self, session_id: str) -> str:
        if session_id in self._results:
            return (
                SessionStatus.COMPLETED
                if self._results[session_id].exit_code == 0
                else SessionStatus.FAILED
            )
        session = self._sessions.get(session_id)
        if session is None:
            return "not_found"
        return session.status.value

    def get_result(self, session_id: str) -> SessionResult | None:
        return self._results.get(session_id)

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions = []
        for sid, session in self._sessions.items():
            result = self._results.get(sid)
            sessions.append(
                {
                    "session_id": sid,
                    "tool": "codex" if isinstance(session, CodexSession) else "claude",
                    "status": self.get_status(sid),
                    "exit_code": result.exit_code if result else None,
                }
            )
        return sessions

    async def terminate(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            return
        await session.terminate()
        task = self._tasks.get(session_id)
        if task and not task.done():
            task.cancel()

    def _persist_result(self, result: SessionResult) -> None:
        path = self._sessions_dir / f"{result.session_id}.json"
        data = {
            "session_id": result.session_id,
            "task": result.task,
            "output": result.output[:10000],
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "model": result.model,
            "tool": result.tool,
        }
        path.write_text(json.dumps(data, indent=2))
