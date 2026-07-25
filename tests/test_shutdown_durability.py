"""Phase 2 shutdown durability: PID ordering, budget flush, duplicate start."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from hive.agents.state import AgentState, AgentStatus
from hive.checkpoint import CheckpointManager
from hive.config import HiveConfig, set_config
from hive.daemon.loop import HiveDaemon
from hive.daemon.run_lifecycle import DaemonAlreadyRunningError, RunLifecycle
from hive.memory.store import HiveStore


@pytest.fixture
def hive_dir(tmp_path: Path) -> Path:
    hive = tmp_path / ".hive"
    hive.mkdir()
    for sub in ("sessions", "workspaces", "comms", "agent_memory", "checkpoints"):
        (hive / sub).mkdir()
    cfg = HiveConfig()
    cfg.economy.enabled = False
    set_config(cfg)
    cfg.save(hive)
    return hive


async def _seed_agent(store: HiveStore, name: str = "worker") -> AgentState:
    state = AgentState(
        agent_id=f"{name}-test0001",
        name=name,
        role="test agent",
        model="mock-model",
        status=AgentStatus.IDLE,
        workspace=".",
    )
    await store.save_agent(state)
    return state


class TestShutdownOrdering:
    @pytest.mark.asyncio
    async def test_pid_exists_during_checkpoint_removed_after_shutdown(
        self, hive_dir: Path
    ) -> None:
        """PID lockfile stays until checkpoints and budget flush complete."""
        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        agent = await _seed_agent(store)

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")
        pid_file = hive_dir / "daemon.pid"
        pid_file.write_text(str(os.getpid()))

        pid_seen_during_checkpoint = False

        original_save = daemon._checkpoint.save

        def _save_with_pid_check(*args: object, **kwargs: object) -> None:
            nonlocal pid_seen_during_checkpoint
            assert pid_file.exists(), "PID must exist while checkpoints run"
            pid_seen_during_checkpoint = True
            original_save(*args, **kwargs)

        daemon._checkpoint.save = _save_with_pid_check  # type: ignore[method-assign]

        await daemon._shutdown()

        assert pid_seen_during_checkpoint
        assert not pid_file.exists()

        cps = CheckpointManager(hive_dir).list_checkpoints(agent.agent_id)
        assert cps and cps[0].label == "daemon_shutdown"

    @pytest.mark.asyncio
    async def test_budget_flushed_on_shutdown(self, hive_dir: Path) -> None:
        """Graceful shutdown persists budget ledger when budget_persist is enabled."""
        cfg = HiveConfig.load(hive_dir)
        cfg.daemon.budget_persist = True
        cfg.daemon.budget_usd = 5.0
        set_config(cfg)
        cfg.save(hive_dir)

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")
        await daemon.budget.record(cost_usd=2.50, tokens=120)

        ledger = hive_dir / "budget.json"
        assert not ledger.exists()

        await daemon._shutdown()

        assert ledger.exists()
        data = ledger.read_text()
        assert "2.5" in data
        assert "120" in data


class TestDuplicateStart:
    @pytest.mark.asyncio
    async def test_raises_when_live_pid_exists(self, hive_dir: Path) -> None:
        """Second start against a live PID raises DaemonAlreadyRunningError."""
        pid_file = hive_dir / "daemon.pid"
        pid_file.write_text(str(os.getpid()))

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")
        lifecycle = RunLifecycle(daemon, daemon._agent_context)

        with pytest.raises(DaemonAlreadyRunningError, match="already running"):
            await lifecycle.start(max_cycles=0)

    def test_cli_start_exits_nonzero_on_duplicate(self, tmp_path: Path) -> None:
        """hive start surfaces duplicate daemon as exit code 1."""
        from typer.testing import CliRunner

        from hive.cli.main import app

        hive = tmp_path / ".hive"
        hive.mkdir()
        for sub in ("sessions", "workspaces", "comms", "agent_memory", "checkpoints"):
            (hive / sub).mkdir()
        HiveConfig().save(hive)
        pid_file = hive / "daemon.pid"
        pid_file.write_text(str(os.getpid()))
        (tmp_path / "profiles").mkdir()
        (tmp_path / "profiles" / "coder.yaml").write_text("name: coder\nrole: test\nmodel: mock\n")

        runner = CliRunner()
        with patch.object(Path, "cwd", return_value=tmp_path):
            result = runner.invoke(app, ["start", "--profiles", "coder"])

        assert result.exit_code == 1
        assert "already running" in result.output.lower()


class TestBudgetRestartContinuity:
    @pytest.mark.asyncio
    async def test_shutdown_then_new_daemon_reloads_budget(self, hive_dir: Path) -> None:
        """Spent totals survive stop/start via shutdown budget flush."""
        cfg = HiveConfig.load(hive_dir)
        cfg.daemon.budget_persist = True
        cfg.daemon.budget_usd = 10.0
        set_config(cfg)
        cfg.save(hive_dir)

        daemon1 = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")
        await daemon1.budget.record(cost_usd=3.75, tokens=200)
        await daemon1._shutdown()

        daemon2 = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs2")
        assert daemon2.budget.spent_usd == 3.75
        assert daemon2.budget.spent_tokens == 200
