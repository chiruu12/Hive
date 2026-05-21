"""Tests for OrchestratorToolkit."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hive.orchestrator.manager import SessionManager
from hive.orchestrator.toolkit import OrchestratorToolkit


class TestOrchestratorToolkit:
    @pytest.fixture
    def toolkit(self, tmp_path: Path) -> OrchestratorToolkit:
        hive_dir = tmp_path / ".hive"
        hive_dir.mkdir()
        manager = SessionManager(hive_dir)
        tk = OrchestratorToolkit(manager)
        tk.bind("test-agent")
        return tk

    def test_tool_discovery(self, toolkit):
        tools = toolkit.get_tools()
        names = {t.name for t in tools}
        assert names == {
            "run_code_task",
            "check_task_status",
            "list_code_tasks",
            "review_task_output",
        }

    def test_has_instructions(self, toolkit):
        assert "orchestration" in toolkit.instructions.lower()

    @pytest.mark.asyncio
    @patch("hive.orchestrator.session.asyncio.create_subprocess_exec")
    async def test_run_code_task(self, mock_exec, toolkit, tmp_path):
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"task done", b""))
        proc.returncode = 0
        proc.terminate = MagicMock()
        proc.kill = MagicMock()
        proc.wait = AsyncMock()
        mock_exec.return_value = proc

        workspace = tmp_path / "project"
        workspace.mkdir()
        result = await toolkit.run_code_task(
            task="build api",
            workspace=str(workspace),
            cli_tool="claude",
            model="sonnet",
        )
        data = json.loads(result)
        assert data["status"] == "completed"
        assert "task done" in data["output"]
        assert data["tool"] == "claude"

    @pytest.mark.asyncio
    async def test_run_code_task_bad_workspace(self, toolkit):
        result = await toolkit.run_code_task(
            task="test",
            workspace="/nonexistent/path/xyz",
        )
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_list_code_tasks_empty(self, toolkit):
        result = await toolkit.list_code_tasks()
        assert result == "No code tasks."

    @pytest.mark.asyncio
    async def test_check_unknown_session(self, toolkit):
        result = await toolkit.check_task_status("nonexistent")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_review_unknown_session(self, toolkit):
        result = await toolkit.review_task_output("nonexistent")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    @patch("hive.orchestrator.session.asyncio.create_subprocess_exec")
    async def test_review_task_output(self, mock_exec, toolkit, tmp_path):
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"full output here", b""))
        proc.returncode = 0
        proc.terminate = MagicMock()
        proc.kill = MagicMock()
        proc.wait = AsyncMock()
        mock_exec.return_value = proc

        workspace = tmp_path / "project"
        workspace.mkdir()
        run_result = await toolkit.run_code_task(
            task="build",
            workspace=str(workspace),
        )
        data = json.loads(run_result)
        session_id = data["session_id"]

        review = await toolkit.review_task_output(session_id)
        review_data = json.loads(review)
        assert review_data["task"] == "build"
        assert "full output here" in review_data["output"]
