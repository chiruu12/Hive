"""Adversarial tests: orchestrator workspace escape attempts.

These tests verify OrchestratorToolkit restricts run_code_task workspaces
to the agent's own directory when set_workspace() has been called.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hive.orchestrator.manager import SessionManager
from hive.orchestrator.toolkit import OrchestratorToolkit


@pytest.fixture
def agent_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "agent-workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def restricted_toolkit(tmp_path: Path, agent_workspace: Path) -> OrchestratorToolkit:
    hive_dir = tmp_path / ".hive"
    hive_dir.mkdir()
    manager = SessionManager(hive_dir)
    tk = OrchestratorToolkit(manager, workspace=agent_workspace)
    tk.bind("test-agent")
    return tk


@pytest.fixture
def restricted_toolkit_via_set_workspace(
    tmp_path: Path, agent_workspace: Path
) -> OrchestratorToolkit:
    """Legacy set_workspace path kept for backward compatibility."""
    hive_dir = tmp_path / ".hive"
    hive_dir.mkdir()
    manager = SessionManager(hive_dir)
    tk = OrchestratorToolkit(manager)
    tk.bind("test-agent")
    tk.set_workspace(agent_workspace)
    return tk


@pytest.fixture
def permissive_toolkit(tmp_path: Path) -> OrchestratorToolkit:
    """Toolkit without set_workspace — backward-compatible permissive mode."""
    hive_dir = tmp_path / ".hive"
    hive_dir.mkdir()
    manager = SessionManager(hive_dir)
    tk = OrchestratorToolkit(manager)
    tk.bind("test-agent")
    return tk


def _mock_subprocess(mock_exec: MagicMock) -> None:
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(b"task done", b""))
    proc.returncode = 0
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    mock_exec.return_value = proc


class TestWorkspaceContainment:
    @pytest.mark.asyncio
    async def test_outside_workspace_rejected(
        self, restricted_toolkit: OrchestratorToolkit, agent_workspace: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        result = await restricted_toolkit.run_code_task(
            task="malicious",
            workspace=str(outside),
        )
        assert "outside your allowed workspace" in result
        assert str(agent_workspace) in result

    @pytest.mark.asyncio
    async def test_parent_escape_via_dotdot_rejected(
        self, restricted_toolkit: OrchestratorToolkit, agent_workspace: Path, tmp_path: Path
    ) -> None:
        escape = agent_workspace / ".." / "escape"
        escape.mkdir()
        result = await restricted_toolkit.run_code_task(
            task="escape",
            workspace=str(escape),
        )
        assert "outside your allowed workspace" in result

    @pytest.mark.asyncio
    async def test_dotdot_in_path_string_rejected(
        self, restricted_toolkit: OrchestratorToolkit, agent_workspace: Path, tmp_path: Path
    ) -> None:
        sibling = tmp_path / "sibling"
        sibling.mkdir()
        dotted = str(agent_workspace / ".." / "sibling")
        result = await restricted_toolkit.run_code_task(
            task="escape",
            workspace=dotted,
        )
        assert "outside your allowed workspace" in result

    @pytest.mark.asyncio
    async def test_absolute_sensitive_path_rejected(
        self, restricted_toolkit: OrchestratorToolkit
    ) -> None:
        if not Path("/etc").is_dir():
            pytest.skip("/etc not available")
        result = await restricted_toolkit.run_code_task(
            task="attack",
            workspace="/etc",
        )
        assert "outside your allowed workspace" in result

    @pytest.mark.asyncio
    async def test_symlink_escape_rejected(
        self, restricted_toolkit: OrchestratorToolkit, agent_workspace: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "secret"
        target.mkdir()
        link = agent_workspace / "innocent"
        link.symlink_to(target)
        result = await restricted_toolkit.run_code_task(
            task="symlink escape",
            workspace=str(link),
        )
        assert "outside your allowed workspace" in result

    @pytest.mark.asyncio
    @patch("hive.orchestrator.session.asyncio.create_subprocess_exec")
    async def test_subdir_allowed(
        self,
        mock_exec: MagicMock,
        restricted_toolkit: OrchestratorToolkit,
        agent_workspace: Path,
    ) -> None:
        _mock_subprocess(mock_exec)
        subdir = agent_workspace / "project"
        subdir.mkdir()
        result = await restricted_toolkit.run_code_task(
            task="build",
            workspace=str(subdir),
        )
        assert "outside your allowed workspace" not in result
        data = json.loads(result)
        assert data["status"] == "completed"

    @pytest.mark.asyncio
    @patch("hive.orchestrator.session.asyncio.create_subprocess_exec")
    async def test_agent_workspace_root_allowed(
        self,
        mock_exec: MagicMock,
        restricted_toolkit: OrchestratorToolkit,
        agent_workspace: Path,
    ) -> None:
        _mock_subprocess(mock_exec)
        result = await restricted_toolkit.run_code_task(
            task="build",
            workspace=str(agent_workspace),
        )
        assert "outside your allowed workspace" not in result
        data = json.loads(result)
        assert data["status"] == "completed"


class TestConstructorWorkspace:
    @pytest.mark.asyncio
    async def test_constructor_workspace_containment(
        self,
        restricted_toolkit: OrchestratorToolkit,
        agent_workspace: Path,
        tmp_path: Path,
    ) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        result = await restricted_toolkit.run_code_task(
            task="malicious",
            workspace=str(outside),
        )
        assert "outside your allowed workspace" in result
        assert str(agent_workspace) in result


class TestBackwardCompatibility:
    @pytest.mark.asyncio
    @patch("hive.orchestrator.session.asyncio.create_subprocess_exec")
    async def test_no_set_workspace_is_permissive(
        self,
        mock_exec: MagicMock,
        permissive_toolkit: OrchestratorToolkit,
        tmp_path: Path,
    ) -> None:
        _mock_subprocess(mock_exec)
        outside = tmp_path / "anywhere"
        outside.mkdir()
        result = await permissive_toolkit.run_code_task(
            task="test",
            workspace=str(outside),
        )
        assert "outside your allowed workspace" not in result
        data = json.loads(result)
        assert data["status"] == "completed"

    @pytest.mark.asyncio
    async def test_set_workspace_after_bind_keeps_containment(
        self,
        restricted_toolkit_via_set_workspace: OrchestratorToolkit,
        tmp_path: Path,
    ) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        result = await restricted_toolkit_via_set_workspace.run_code_task(
            task="malicious",
            workspace=str(outside),
        )
        assert "outside your allowed workspace" in result


class TestBindPreservesWorkspace:
    @pytest.mark.asyncio
    async def test_bind_after_set_workspace_keeps_containment(
        self, tmp_path: Path, agent_workspace: Path
    ) -> None:
        hive_dir = tmp_path / ".hive"
        hive_dir.mkdir()
        manager = SessionManager(hive_dir)
        tk = OrchestratorToolkit(manager)
        tk.set_workspace(agent_workspace)
        tk.bind("test-agent")

        outside = tmp_path / "outside"
        outside.mkdir()
        result = await tk.run_code_task(task="malicious", workspace=str(outside))
        assert "outside your allowed workspace" in result


class TestOrchestratorEnvScrubbing:
    @pytest.mark.asyncio
    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-leaked", "PATH": "/usr/bin"})
    @patch("hive.orchestrator.session.asyncio.create_subprocess_exec")
    async def test_child_env_strips_provider_secrets(
        self,
        mock_exec: MagicMock,
        tmp_path: Path,
        agent_workspace: Path,
    ) -> None:
        _mock_subprocess(mock_exec)
        hive_dir = tmp_path / ".hive"
        hive_dir.mkdir()
        manager = SessionManager(hive_dir)
        tk = OrchestratorToolkit(manager, workspace=agent_workspace)
        tk.bind("test-agent")

        await tk.run_code_task(task="build", workspace=str(agent_workspace))

        assert mock_exec.called
        env = mock_exec.call_args.kwargs.get("env") or mock_exec.call_args[1].get("env")
        assert env is not None
        assert "ANTHROPIC_API_KEY" not in env
        assert env.get("PATH") == "/usr/bin"
