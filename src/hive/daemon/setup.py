"""Daemon setup - initialize .hive/ directory structure."""

import asyncio
from pathlib import Path

from hive.config import HiveConfig
from hive.memory.store import HiveStore


def ensure_hive_dirs(target: Path | None = None) -> Path:
    """Create the .hive/ directory structure (no DB init). Idempotent.

    Synchronous and loop-safe -- unlike :func:`initialize_hive` it does not call
    ``asyncio.run``, so it can be used from inside a running event loop (e.g. the
    Hive facade's async context manager). Returns the ``.hive`` path.
    """
    root = target or Path.cwd()
    hive_dir = root / ".hive"
    hive_dir.mkdir(exist_ok=True)
    (hive_dir / "sessions").mkdir(exist_ok=True)
    (hive_dir / "workspaces").mkdir(exist_ok=True)

    config_path = hive_dir / "config.yaml"
    if not config_path.exists():
        HiveConfig().save(hive_dir)

    _ensure_gitignore_entry(root / ".gitignore", ".hive/")
    return hive_dir


def initialize_hive(target: Path | None = None) -> None:
    """Create .hive/ directory with required structure and initialize the DB."""
    hive_dir = ensure_hive_dirs(target)
    asyncio.run(HiveStore(hive_dir / "hive.db").initialize())


def _ensure_gitignore_entry(gitignore_path: Path, entry: str) -> None:
    if gitignore_path.exists():
        content = gitignore_path.read_text()
        if entry in content:
            return
        if not content.endswith("\n"):
            content += "\n"
        content += entry + "\n"
        gitignore_path.write_text(content)
    else:
        gitignore_path.write_text(entry + "\n")
