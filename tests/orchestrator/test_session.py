"""Tests for CodeSession protocol, ClaudeCodeSession, and CodexSession."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hive.orchestrator.session import (
    ClaudeCodeSession,
    CodexSession,
    SessionResult,
    SessionStatus,
)


def _mock_process(stdout: bytes = b"output", stderr: bytes = b"", returncode: int = 0):
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


class TestSessionResult:
    def test_fields(self):
        r = SessionResult(
            session_id="s1",
            task="build api",
            output="done",
            exit_code=0,
            duration_ms=1234,
            model="sonnet",
            tool="claude",
        )
        assert r.session_id == "s1"
        assert r.tool == "claude"
        assert r.exit_code == 0
        assert r.duration_ms == 1234


class TestClaudeCodeSession:
    def test_initial_status(self):
        s = ClaudeCodeSession(task="test", workspace="/tmp")
        assert s.status == SessionStatus.PENDING
        assert s.session_id.startswith("claude-")

    @pytest.mark.asyncio
    @patch("hive.orchestrator.session.asyncio.create_subprocess_exec")
    async def test_start_and_wait(self, mock_exec):
        proc = _mock_process(stdout=b"result text")
        mock_exec.return_value = proc

        s = ClaudeCodeSession(task="build api", workspace="/w", model="sonnet")
        result = await s.wait()

        mock_exec.assert_called_once_with(
            "claude",
            "-p",
            "build api",
            "--model",
            "sonnet",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd="/w",
        )
        assert result.output == "result text"
        assert result.exit_code == 0
        assert result.tool == "claude"
        assert result.model == "sonnet"
        assert s.status == SessionStatus.COMPLETED

    @pytest.mark.asyncio
    @patch("hive.orchestrator.session.asyncio.create_subprocess_exec")
    async def test_stderr_appended(self, mock_exec):
        proc = _mock_process(stdout=b"out", stderr=b"warning")
        mock_exec.return_value = proc

        s = ClaudeCodeSession(task="t", workspace="/w")
        result = await s.wait()

        assert "out" in result.output
        assert "STDERR:\nwarning" in result.output

    @pytest.mark.asyncio
    @patch("hive.orchestrator.session.asyncio.create_subprocess_exec")
    async def test_failed_exit_code(self, mock_exec):
        proc = _mock_process(stdout=b"", stderr=b"error", returncode=1)
        mock_exec.return_value = proc

        s = ClaudeCodeSession(task="bad task", workspace="/w")
        result = await s.wait()

        assert result.exit_code == 1
        assert s.status == SessionStatus.FAILED

    @pytest.mark.asyncio
    @patch("hive.orchestrator.session.asyncio.create_subprocess_exec")
    async def test_timeout(self, mock_exec):
        proc = AsyncMock()
        proc.communicate = AsyncMock(side_effect=TimeoutError)
        proc.returncode = None
        proc.terminate = MagicMock()
        proc.kill = MagicMock()
        proc.wait = AsyncMock()
        mock_exec.return_value = proc

        s = ClaudeCodeSession(task="slow", workspace="/w", timeout=1)
        result = await s.wait()

        assert s.status == SessionStatus.TIMEOUT
        assert result.exit_code == -1
        assert "timed out" in result.output

    @pytest.mark.asyncio
    @patch("hive.orchestrator.session.asyncio.create_subprocess_exec")
    async def test_terminate(self, mock_exec):
        proc = _mock_process()
        proc.returncode = None
        mock_exec.return_value = proc

        s = ClaudeCodeSession(task="t", workspace="/w")
        await s.start()
        await s.terminate()
        assert s.status == SessionStatus.FAILED

    @pytest.mark.asyncio
    @patch("hive.orchestrator.session.asyncio.create_subprocess_exec")
    async def test_custom_session_id(self, mock_exec):
        proc = _mock_process()
        mock_exec.return_value = proc

        s = ClaudeCodeSession(task="t", workspace="/w", session_id="my-id")
        assert s.session_id == "my-id"
        result = await s.wait()
        assert result.session_id == "my-id"


class TestCodexSession:
    def test_initial_status(self):
        s = CodexSession(task="test", workspace="/tmp")
        assert s.status == SessionStatus.PENDING
        assert s.session_id.startswith("codex-")

    @pytest.mark.asyncio
    @patch("hive.orchestrator.session.asyncio.create_subprocess_exec")
    async def test_start_and_wait(self, mock_exec):
        proc = _mock_process(stdout=b"codex output")
        mock_exec.return_value = proc

        s = CodexSession(task="write tests", workspace="/w", model="o4-mini")
        result = await s.wait()

        mock_exec.assert_called_once_with(
            "codex",
            "--model",
            "o4-mini",
            "write tests",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd="/w",
        )
        assert result.output == "codex output"
        assert result.tool == "codex"
        assert result.model == "o4-mini"
        assert s.status == SessionStatus.COMPLETED

    @pytest.mark.asyncio
    @patch("hive.orchestrator.session.asyncio.create_subprocess_exec")
    async def test_timeout(self, mock_exec):
        proc = AsyncMock()
        proc.communicate = AsyncMock(side_effect=TimeoutError)
        proc.returncode = None
        proc.terminate = MagicMock()
        proc.kill = MagicMock()
        proc.wait = AsyncMock()
        mock_exec.return_value = proc

        s = CodexSession(task="slow", workspace="/w", timeout=1)
        result = await s.wait()

        assert s.status == SessionStatus.TIMEOUT
        assert result.exit_code == -1
