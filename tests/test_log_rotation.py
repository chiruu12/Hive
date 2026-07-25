"""Tests for log rotation and run cleanup."""

from __future__ import annotations

from pathlib import Path

from hive.logging.writer import LogWriter


class TestLogRotation:
    def test_cleanup_old_runs(self, tmp_path: Path):
        writer = LogWriter(tmp_path)
        runs_dir = tmp_path / "runs"

        # Create 5 fake run directories
        for i in range(5):
            d = runs_dir / f"run-20250101-00000{i}-abc{i:03d}"
            d.mkdir()
            (d / "run.json").write_text("{}")

        # Keep only 3
        deleted = writer.cleanup_old_runs(3)
        assert deleted == 2
        remaining = [d for d in runs_dir.iterdir() if d.is_dir()]
        assert len(remaining) == 3

    def test_cleanup_noop_when_under_limit(self, tmp_path: Path):
        writer = LogWriter(tmp_path)
        runs_dir = tmp_path / "runs"

        for i in range(3):
            d = runs_dir / f"run-20250101-00000{i}-abc{i:03d}"
            d.mkdir()

        deleted = writer.cleanup_old_runs(5)
        assert deleted == 0
        remaining = [d for d in runs_dir.iterdir() if d.is_dir()]
        assert len(remaining) == 3

    def test_cleanup_unlimited_when_zero(self, tmp_path: Path):
        writer = LogWriter(tmp_path)
        runs_dir = tmp_path / "runs"

        for i in range(10):
            d = runs_dir / f"run-20250101-00000{i}-abc{i:03d}"
            d.mkdir()

        deleted = writer.cleanup_old_runs(0)
        assert deleted == 0

    def test_cleanup_preserves_newest(self, tmp_path: Path):
        writer = LogWriter(tmp_path)
        runs_dir = tmp_path / "runs"

        names = []
        for i in range(5):
            name = f"run-2025010{i + 1}-000000-abc{i:03d}"
            names.append(name)
            d = runs_dir / name
            d.mkdir()
            (d / "run.json").write_text("{}")

        writer.cleanup_old_runs(2)
        remaining = sorted(d.name for d in runs_dir.iterdir() if d.is_dir())
        assert len(remaining) == 2
        # Newest should survive
        assert names[-1] in remaining
        assert names[-2] in remaining
