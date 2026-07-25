"""One-time migration from legacy JSON key-value memory files."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from hive.memory.semantic import SemanticMemory

logger = logging.getLogger(__name__)

MIGRATION_MARKER = ".legacy_json_migrated"


def legacy_json_path(hive_dir: Path, agent_id: str, legacy_dir: Path | None = None) -> Path:
    base = legacy_dir if legacy_dir is not None else hive_dir / "agent_memory"
    return base / f"{agent_id}.json"


def migration_marker_path(hive_dir: Path, agent_id: str) -> Path:
    return hive_dir / "memory" / agent_id / MIGRATION_MARKER


async def migrate_legacy_json(
    semantic: SemanticMemory,
    hive_dir: Path,
    agent_id: str,
    legacy_dir: Path | None = None,
) -> int:
    """Import a legacy JSON KV file into the semantic store.

    Idempotent: writes a marker file so subsequent starts skip import.
    Returns the number of keys imported (0 when already migrated or no file).
    """
    marker = migration_marker_path(hive_dir, agent_id)
    if marker.exists():
        return 0

    json_path = legacy_json_path(hive_dir, agent_id, legacy_dir)
    marker.parent.mkdir(parents=True, exist_ok=True)

    if not json_path.exists():
        marker.write_text("no_legacy_file\n")
        return 0

    try:
        raw = json.loads(json_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Skipping corrupt legacy memory file %s: %s", json_path, exc)
        marker.write_text("corrupt_legacy_file\n")
        return 0

    if not isinstance(raw, dict):
        marker.write_text("invalid_legacy_shape\n")
        return 0

    count = 0
    for key, value in raw.items():
        await semantic.store(
            str(value),
            metadata={"type": "kv", "key": str(key), "source": "legacy_json"},
        )
        count += 1

    marker.write_text(f"imported={count}\n")
    logger.info("Migrated %d legacy memory keys for agent %s", count, agent_id)
    return count


def ensure_legacy_migrated(
    semantic: SemanticMemory,
    hive_dir: Path,
    agent_id: str,
    legacy_dir: Path | None = None,
) -> int:
    """Sync wrapper used by the daemon memory cache on first access."""
    from hive.memory._sync import run_async

    return run_async(migrate_legacy_json(semantic, hive_dir, agent_id, legacy_dir))
