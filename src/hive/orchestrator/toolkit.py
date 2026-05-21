"""Orchestrator toolkit — tools for driving Claude Code and Codex CLI sessions."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from hive.orchestrator.manager import SessionManager
from hive.tools.base import Toolkit, tool

logger = logging.getLogger(__name__)


class OrchestratorToolkit(Toolkit):
    """Tools for running and managing Claude Code / Codex CLI sessions."""

    def __init__(self, manager: SessionManager):
        self._manager = manager

    @property
    def instructions(self) -> str:
        return (
            "You have access to code orchestration tools that can run tasks using "
            "Claude Code or Codex CLI. Use run_code_task to execute coding tasks "
            "in a workspace directory. Each task runs as a subprocess and returns "
            "the CLI output when complete."
        )

    @tool()
    async def run_code_task(
        self,
        task: str,
        workspace: str,
        cli_tool: str = "claude",
        model: str = "sonnet",
    ) -> str:
        """Run a coding task using Claude Code or Codex CLI and return the result.

        Args:
            task: Description of the coding task to perform.
            workspace: Directory path where the task should be executed.
            cli_tool: Which CLI to use — "claude" or "codex".
            model: Model name to pass to the CLI.
        """
        workspace_path = Path(workspace).resolve()
        if not workspace_path.is_dir():
            return f"Error: workspace directory does not exist: {workspace}"

        session_id = await self._manager.create(
            task=task,
            workspace=str(workspace_path),
            tool=cli_tool,
            model=model,
        )

        bg_task = self._manager._tasks.get(session_id)
        if bg_task:
            await bg_task

        result = self._manager.get_result(session_id)
        if result is None:
            return f"Session {session_id} completed but no result available."

        return json.dumps(
            {
                "session_id": result.session_id,
                "status": "completed" if result.exit_code == 0 else "failed",
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "model": result.model,
                "tool": result.tool,
                "output": result.output[:5000],
            }
        )

    @tool()
    async def check_task_status(self, session_id: str) -> str:
        """Check the status of a running or completed code task.

        Args:
            session_id: The session ID returned from run_code_task.
        """
        status = self._manager.get_status(session_id)
        if status == "not_found":
            return f"Session not found: {session_id}"
        return json.dumps({"session_id": session_id, "status": status})

    @tool()
    async def list_code_tasks(self) -> str:
        """List all code tasks (running and completed)."""
        sessions = self._manager.list_sessions()
        if not sessions:
            return "No code tasks."
        return json.dumps(sessions)

    @tool()
    async def review_task_output(self, session_id: str) -> str:
        """Review the full output of a completed code task.

        Args:
            session_id: The session ID to review.
        """
        result = self._manager.get_result(session_id)
        if result is None:
            status = self._manager.get_status(session_id)
            if status == "not_found":
                return f"Session not found: {session_id}"
            return f"Session {session_id} is still {status}. Wait for completion."
        return json.dumps(
            {
                "session_id": result.session_id,
                "task": result.task,
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "output": result.output,
            }
        )
