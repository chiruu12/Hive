"""Code session protocol and implementations for Claude Code and Codex CLI."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

logger = logging.getLogger(__name__)


class SessionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class SessionResult:
    session_id: str
    task: str
    output: str
    exit_code: int
    duration_ms: int
    model: str
    tool: str


class CodeSession(Protocol):
    @property
    def session_id(self) -> str: ...

    @property
    def status(self) -> SessionStatus: ...

    async def start(self) -> None: ...

    async def wait(self) -> SessionResult: ...

    async def terminate(self) -> None: ...


class ClaudeCodeSession:
    """Wraps `claude -p "{task}" --model {model}` as an async subprocess."""

    def __init__(
        self,
        task: str,
        workspace: str,
        model: str = "sonnet",
        timeout: int = 300,
        session_id: str = "",
    ):
        self._task = task
        self._workspace = workspace
        self._model = model
        self._timeout = timeout
        self._session_id = session_id or f"claude-{uuid4().hex[:8]}"
        self._status = SessionStatus.PENDING
        self._process: asyncio.subprocess.Process | None = None
        self._start_time: float = 0.0

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def status(self) -> SessionStatus:
        return self._status

    async def start(self) -> None:
        self._start_time = time.time()
        self._status = SessionStatus.RUNNING
        self._process = await asyncio.create_subprocess_exec(
            "claude",
            "-p",
            self._task,
            "--model",
            self._model,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._workspace,
        )

    async def wait(self) -> SessionResult:
        if self._process is None:
            await self.start()
        assert self._process is not None

        try:
            stdout, stderr = await asyncio.wait_for(
                self._process.communicate(),
                timeout=self._timeout,
            )
            exit_code = self._process.returncode or 0
            output = stdout.decode(errors="replace")
            if stderr:
                err_text = stderr.decode(errors="replace").strip()
                if err_text:
                    output += f"\n\nSTDERR:\n{err_text}"
            self._status = SessionStatus.COMPLETED if exit_code == 0 else SessionStatus.FAILED
        except TimeoutError:
            self._status = SessionStatus.TIMEOUT
            await self.terminate()
            exit_code = -1
            output = f"Session timed out after {self._timeout}s"

        duration_ms = int((time.time() - self._start_time) * 1000)
        return SessionResult(
            session_id=self._session_id,
            task=self._task,
            output=output,
            exit_code=exit_code,
            duration_ms=duration_ms,
            model=self._model,
            tool="claude",
        )

    async def terminate(self) -> None:
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except (TimeoutError, ProcessLookupError):
                self._process.kill()
        if self._status not in (SessionStatus.TIMEOUT, SessionStatus.COMPLETED):
            self._status = SessionStatus.FAILED


class CodexSession:
    """Wraps `codex --model {model} "{task}"` as an async subprocess."""

    def __init__(
        self,
        task: str,
        workspace: str,
        model: str = "o4-mini",
        timeout: int = 300,
        session_id: str = "",
    ):
        self._task = task
        self._workspace = workspace
        self._model = model
        self._timeout = timeout
        self._session_id = session_id or f"codex-{uuid4().hex[:8]}"
        self._status = SessionStatus.PENDING
        self._process: asyncio.subprocess.Process | None = None
        self._start_time: float = 0.0

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def status(self) -> SessionStatus:
        return self._status

    async def start(self) -> None:
        self._start_time = time.time()
        self._status = SessionStatus.RUNNING
        self._process = await asyncio.create_subprocess_exec(
            "codex",
            "--model",
            self._model,
            self._task,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._workspace,
        )

    async def wait(self) -> SessionResult:
        if self._process is None:
            await self.start()
        assert self._process is not None

        try:
            stdout, stderr = await asyncio.wait_for(
                self._process.communicate(),
                timeout=self._timeout,
            )
            exit_code = self._process.returncode or 0
            output = stdout.decode(errors="replace")
            if stderr:
                err_text = stderr.decode(errors="replace").strip()
                if err_text:
                    output += f"\n\nSTDERR:\n{err_text}"
            self._status = SessionStatus.COMPLETED if exit_code == 0 else SessionStatus.FAILED
        except TimeoutError:
            self._status = SessionStatus.TIMEOUT
            await self.terminate()
            exit_code = -1
            output = f"Session timed out after {self._timeout}s"

        duration_ms = int((time.time() - self._start_time) * 1000)
        return SessionResult(
            session_id=self._session_id,
            task=self._task,
            output=output,
            exit_code=exit_code,
            duration_ms=duration_ms,
            model=self._model,
            tool="codex",
        )

    async def terminate(self) -> None:
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except (TimeoutError, ProcessLookupError):
                self._process.kill()
        if self._status not in (SessionStatus.TIMEOUT, SessionStatus.COMPLETED):
            self._status = SessionStatus.FAILED
