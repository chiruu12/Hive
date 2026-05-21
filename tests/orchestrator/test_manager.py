"""Tests for SessionManager."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hive.orchestrator.manager import SessionManager


def _mock_process(stdout: bytes = b"output", stderr: bytes = b"", returncode: int = 0):
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


class TestSessionManager:
    @pytest.fixture
    def manager(self, tmp_path: Path) -> SessionManager:
        hive_dir = tmp_path / ".hive"
        hive_dir.mkdir()
        return SessionManager(hive_dir, max_concurrent=2)

    @pytest.mark.asyncio
    @patch("hive.orchestrator.session.asyncio.create_subprocess_exec")
    async def test_create_returns_session_id(self, mock_exec, manager):
        mock_exec.return_value = _mock_process()

        sid = await manager.create("build api", "/workspace", tool="claude")
        assert sid.startswith("claude-")

    @pytest.mark.asyncio
    @patch("hive.orchestrator.session.asyncio.create_subprocess_exec")
    async def test_create_codex_session(self, mock_exec, manager):
        mock_exec.return_value = _mock_process()

        sid = await manager.create("write tests", "/w", tool="codex")
        assert sid.startswith("codex-")

    @pytest.mark.asyncio
    @patch("hive.orchestrator.session.asyncio.create_subprocess_exec")
    async def test_get_result_after_completion(self, mock_exec, manager):
        mock_exec.return_value = _mock_process(stdout=b"done")

        sid = await manager.create("task", "/w")
        await manager.await_session(sid)

        result = manager.get_result(sid)
        assert result is not None
        assert result.output == "done"
        assert result.exit_code == 0

    @pytest.mark.asyncio
    @patch("hive.orchestrator.session.asyncio.create_subprocess_exec")
    async def test_get_status(self, mock_exec, manager):
        mock_exec.return_value = _mock_process()

        sid = await manager.create("task", "/w")
        await manager.await_session(sid)

        status = manager.get_status(sid)
        assert status == "completed"

    @pytest.mark.asyncio
    async def test_get_status_not_found(self, manager):
        assert manager.get_status("nonexistent") == "not_found"

    @pytest.mark.asyncio
    @patch("hive.orchestrator.session.asyncio.create_subprocess_exec")
    async def test_list_sessions(self, mock_exec, manager):
        mock_exec.return_value = _mock_process()

        await manager.create("t1", "/w")
        await manager.create("t2", "/w", tool="codex")
        sessions = manager.list_sessions()
        assert len(sessions) == 2
        tools = {s["tool"] for s in sessions}
        assert tools == {"claude", "codex"}

    @pytest.mark.asyncio
    @patch("hive.orchestrator.session.asyncio.create_subprocess_exec")
    async def test_persistence(self, mock_exec, manager):
        mock_exec.return_value = _mock_process(stdout=b"result")

        sid = await manager.create("task", "/w")
        await manager.await_session(sid)

        json_path = manager._sessions_dir / f"{sid}.json"
        assert json_path.exists()

    @pytest.mark.asyncio
    @patch("hive.orchestrator.session.asyncio.create_subprocess_exec")
    async def test_semaphore_limits_concurrency(self, mock_exec, manager):
        started = []
        event = asyncio.Event()

        original_mock = _mock_process()

        async def slow_communicate():
            started.append(1)
            await event.wait()
            return (b"ok", b"")

        original_mock.communicate = slow_communicate
        mock_exec.return_value = original_mock

        await manager.create("t1", "/w")
        await manager.create("t2", "/w")
        await manager.create("t3", "/w")
        await asyncio.sleep(0.05)

        # Only 2 should have started (semaphore=2)
        assert len(started) == 2

        event.set()
        await asyncio.sleep(0.05)
        assert len(started) == 3
