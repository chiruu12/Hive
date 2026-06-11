"""Tests for checkpoint save/restore robustness."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from hive.agents.suffering import SufferingState
from hive.checkpoint import CheckpointManager
from hive.context import ExecutionContext
from hive.memory.store import HiveStore


@pytest.fixture
def ctx(tmp_dir: Path) -> ExecutionContext:
    return ExecutionContext(
        store=HiveStore(tmp_dir / "hive.db"),
        comms_dir=tmp_dir / "comms",
        memory_dir=tmp_dir / "memory",
    )


class TestCheckpointRoundTrip:
    def test_save_and_restore(self, tmp_dir: Path, ctx: ExecutionContext) -> None:
        mgr = CheckpointManager(tmp_dir)
        suffering = SufferingState(agent_id="a1")
        cp_id = mgr.save("a1", "test", suffering, None, ctx)

        restored = mgr.restore("a1", cp_id)
        assert restored is not None
        assert restored.label == "test"
        assert restored.suffering_snapshot["agent_id"] == "a1"

    def test_restore_missing_returns_none(self, tmp_dir: Path) -> None:
        mgr = CheckpointManager(tmp_dir)
        assert mgr.restore("a1", "cp-nope") is None


class TestCorruptCheckpoints:
    def test_corrupt_file_quarantined(
        self, tmp_dir: Path, ctx: ExecutionContext, caplog: pytest.LogCaptureFixture
    ) -> None:
        mgr = CheckpointManager(tmp_dir)
        suffering = SufferingState(agent_id="a1")
        cp_id = mgr.save("a1", "good", suffering, None, ctx)

        bad = tmp_dir / "checkpoints" / "a1" / "cp-deadbeef.json"
        bad.write_text("{not valid json")

        with caplog.at_level(logging.WARNING):
            cps = mgr.list_checkpoints("a1")

        # Valid checkpoint survives; corrupt one is moved aside, not silently dropped.
        assert [c.checkpoint_id for c in cps] == [cp_id]
        assert not bad.exists()
        assert bad.with_name(bad.name + ".corrupt").exists()
        assert any("quarantined" in r.message for r in caplog.records)

    def test_quarantine_is_one_time(self, tmp_dir: Path, ctx: ExecutionContext) -> None:
        mgr = CheckpointManager(tmp_dir)
        suffering = SufferingState(agent_id="a1")
        mgr.save("a1", "good", suffering, None, ctx)

        bad = tmp_dir / "checkpoints" / "a1" / "cp-deadbeef.json"
        bad.write_text("{not valid json")

        mgr.list_checkpoints("a1")
        # Second listing no longer sees the corrupt file at all.
        assert len(mgr.list_checkpoints("a1")) == 1
        assert len(list((tmp_dir / "checkpoints" / "a1").glob("*.corrupt"))) == 1


class TestWorldSnapshotFailure:
    def test_save_survives_world_failure_and_warns(
        self, tmp_dir: Path, ctx: ExecutionContext, caplog: pytest.LogCaptureFixture
    ) -> None:
        class BrokenWorld:
            def get_finances(self, agent_id: str) -> None:
                raise RuntimeError("world layer down")

        ctx.world = BrokenWorld()  # type: ignore[assignment]
        mgr = CheckpointManager(tmp_dir)
        suffering = SufferingState(agent_id="a1")

        with caplog.at_level(logging.WARNING):
            cp_id = mgr.save("a1", "crashy", suffering, None, ctx)

        restored = mgr.restore("a1", cp_id)
        assert restored is not None
        assert restored.world_snapshot == {}
        assert any("World snapshot failed" in r.message for r in caplog.records)
