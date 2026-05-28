"""Tests for HiveStore schema: indexes (C1) and versioned migrations (C2)."""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from hive.memory.store import LATEST_SCHEMA_VERSION, HiveStore

# The named indexes created by _SCHEMA. Kept in sync with store._SCHEMA.
EXPECTED_INDEXES = {
    "idx_agents_spawned_at",
    "idx_sessions_agent",
    "idx_goals_agent_status",
    "idx_goals_agent_created",
    "idx_goals_parent",
    "idx_nudges_agent_delivered",
    "idx_schedules_agent_enabled",
    "idx_sub_agents_parent",
    "idx_tasks_agent_status",
    "idx_tasks_status",
    "idx_alarms_agent_status",
    "idx_alarms_status_fire",
}

# agents table as it existed before the spawned_by/max_cycles/cycles_lived columns.
_OLD_AGENTS_SCHEMA = """
CREATE TABLE agents (
    agent_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'idle',
    current_task TEXT,
    steps_completed INTEGER DEFAULT 0,
    steps_total INTEGER DEFAULT 0,
    workspace TEXT DEFAULT '',
    spawned_at TEXT NOT NULL,
    last_active TEXT NOT NULL,
    error TEXT
);
"""


class TestIndexes:
    @pytest.mark.asyncio
    async def test_all_indexes_created(self, tmp_path: Path) -> None:
        store = HiveStore(tmp_path / "state.db")
        await store.initialize()

        async with aiosqlite.connect(tmp_path / "state.db") as db:
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
            names = {row[0] for row in await cursor.fetchall()}

        assert EXPECTED_INDEXES <= names

    @pytest.mark.asyncio
    async def test_hot_goal_query_uses_index(self, tmp_path: Path) -> None:
        """EXPLAIN QUERY PLAN confirms the goals(agent_id, status) index is used."""
        store = HiveStore(tmp_path / "state.db")
        await store.initialize()

        async with aiosqlite.connect(tmp_path / "state.db") as db:
            cursor = await db.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM goals WHERE agent_id = 'a' AND status = 'active'"
            )
            plan = " ".join(str(col) for row in await cursor.fetchall() for col in row)

        assert "idx_goals_agent_status" in plan


class TestMigrations:
    @pytest.mark.asyncio
    async def test_fresh_db_at_latest_version(self, tmp_path: Path) -> None:
        store = HiveStore(tmp_path / "state.db")
        await store.initialize()

        async with aiosqlite.connect(tmp_path / "state.db") as db:
            cursor = await db.execute("PRAGMA user_version")
            row = await cursor.fetchone()

        assert row is not None
        assert row[0] == LATEST_SCHEMA_VERSION

    @pytest.mark.asyncio
    async def test_upgrade_from_v0_adds_columns_and_keeps_data(self, tmp_path: Path) -> None:
        """A version-0 DB missing later columns upgrades cleanly without data loss."""
        db_path = tmp_path / "state.db"

        # Build a pre-migration database: old agents table, user_version 0, one row.
        async with aiosqlite.connect(db_path) as db:
            await db.executescript(_OLD_AGENTS_SCHEMA)
            await db.execute(
                "INSERT INTO agents (agent_id, name, role, model, spawned_at, last_active) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("a1", "Ada", "coder", "claude", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
            )
            await db.execute("PRAGMA user_version = 0")
            await db.commit()

        await HiveStore(db_path).initialize()

        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("PRAGMA user_version")
            version = (await cursor.fetchone())[0]

            cursor = await db.execute("PRAGMA table_info(agents)")
            cols = {row[1] for row in await cursor.fetchall()}

            cursor = await db.execute("SELECT name FROM agents WHERE agent_id = 'a1'")
            row = await cursor.fetchone()

        assert version == LATEST_SCHEMA_VERSION
        assert {"spawned_by", "max_cycles", "cycles_lived"} <= cols
        assert row is not None and row[0] == "Ada"  # pre-existing data survived

    @pytest.mark.asyncio
    async def test_initialize_is_idempotent(self, tmp_path: Path) -> None:
        """Initializing twice is a no-op and does not error or change the version."""
        store = HiveStore(tmp_path / "state.db")
        await store.initialize()
        await store.initialize()

        async with aiosqlite.connect(tmp_path / "state.db") as db:
            cursor = await db.execute("PRAGMA user_version")
            version = (await cursor.fetchone())[0]

        assert version == LATEST_SCHEMA_VERSION
