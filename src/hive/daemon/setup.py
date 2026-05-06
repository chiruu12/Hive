"""Daemon setup - initialize .hive/ directory structure."""

import asyncio
from pathlib import Path

from hive.config import HiveConfig
from hive.memory.store import HiveStore


def initialize_hive(target: Path | None = None) -> None:
    """Create .hive/ directory with required structure."""
    hive_dir = (target or Path.cwd()) / ".hive"
    hive_dir.mkdir(exist_ok=True)
    (hive_dir / "sessions").mkdir(exist_ok=True)
    (hive_dir / "workspaces").mkdir(exist_ok=True)

    db_path = hive_dir / "hive.db"
    store = HiveStore(db_path)
    asyncio.run(store.initialize())

    config_path = hive_dir / "config.yaml"
    if not config_path.exists():
        HiveConfig().save(hive_dir)

    gitignore = (target or Path.cwd()) / ".gitignore"
    _ensure_gitignore_entry(gitignore, ".hive/")


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
