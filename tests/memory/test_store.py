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
    "idx_sessions_user",
    "idx_sessions_user_key",
    "idx_approvals_agent_status",
    "idx_approvals_status",
    "idx_approvals_lookup",
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
    async def test_partial_migration_recovers_on_rerun(self, tmp_path: Path) -> None:
        """A half-applied migration (some columns added, version still 0) recovers.

        The column-existence guards exist precisely so re-running initialize()
        finishes the migration instead of erroring on the already-added column.
        """
        db_path = tmp_path / "state.db"
        async with aiosqlite.connect(db_path) as db:
            await db.executescript(_OLD_AGENTS_SCHEMA)
            # Simulate a crash mid-_migration_1: spawned_by added, the rest not,
            # and user_version never bumped.
            await db.execute("ALTER TABLE agents ADD COLUMN spawned_by TEXT")
            await db.execute("PRAGMA user_version = 0")
            await db.commit()

        await HiveStore(db_path).initialize()  # must not raise on the existing column

        async with aiosqlite.connect(db_path) as db:
            version = (await (await db.execute("PRAGMA user_version")).fetchone())[0]
            cursor = await db.execute("PRAGMA table_info(agents)")
            cols = {row[1] for row in await cursor.fetchall()}

        assert version == LATEST_SCHEMA_VERSION
        assert {"spawned_by", "max_cycles", "cycles_lived"} <= cols

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


# A version-1 database: child tables WITHOUT ON DELETE CASCADE, as they existed
# before migration 2. Subset of tables is enough to exercise the rebuild.
_V1_SCHEMA_NO_CASCADE = """
CREATE TABLE agents (
    agent_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
    model TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'idle', current_task TEXT,
    steps_completed INTEGER DEFAULT 0, steps_total INTEGER DEFAULT 0,
    workspace TEXT DEFAULT '', spawned_at TEXT NOT NULL, last_active TEXT NOT NULL,
    error TEXT, spawned_by TEXT, max_cycles INTEGER, cycles_lived INTEGER DEFAULT 0
);
CREATE TABLE goals (
    goal_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, objective TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active', priority INTEGER DEFAULT 4,
    parent_goal_id TEXT, created_at TEXT NOT NULL, completed_at TEXT,
    steps_completed INTEGER DEFAULT 0,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, description TEXT NOT NULL,
    priority TEXT DEFAULT 'medium', status TEXT DEFAULT 'pending', due_date TEXT,
    created_at TEXT NOT NULL, completed_at TEXT,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);
"""


async def _insert_agent_with_children(db_path: Path) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            "INSERT INTO agents (agent_id, name, role, model, spawned_at, last_active) "
            "VALUES ('a1', 'Ada', 'coder', 'claude', 't', 't')"
        )
        await db.execute(
            "INSERT INTO goals (goal_id, agent_id, objective, created_at) "
            "VALUES ('g1', 'a1', 'obj', 't')"
        )
        await db.execute(
            "INSERT INTO tasks (task_id, agent_id, description, created_at) "
            "VALUES ('t1', 'a1', 'desc', 't')"
        )
        await db.commit()


# A version-2 database: sessions WITHOUT the multi-tenant columns and no approvals
# table, as they existed before migration 3.
_V2_SCHEMA_PRE_TENANT = """
CREATE TABLE agents (
    agent_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
    model TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'idle', current_task TEXT,
    steps_completed INTEGER DEFAULT 0, steps_total INTEGER DEFAULT 0,
    workspace TEXT DEFAULT '', spawned_at TEXT NOT NULL, last_active TEXT NOT NULL,
    error TEXT, spawned_by TEXT, max_cycles INTEGER, cycles_lived INTEGER DEFAULT 0
);
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, task TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running', started_at TEXT NOT NULL,
    completed_at TEXT, input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE
);
"""


class TestMigrationV3:
    @pytest.mark.asyncio
    async def test_v2_to_v3_adds_session_columns_and_approvals(self, tmp_path: Path) -> None:
        """A v2 DB gains the tenant session columns and approvals table, data intact."""
        db_path = tmp_path / "state.db"
        async with aiosqlite.connect(db_path) as db:
            await db.executescript(_V2_SCHEMA_PRE_TENANT)
            await db.execute(
                "INSERT INTO agents (agent_id, name, role, model, spawned_at, last_active) "
                "VALUES ('a1', 'Ada', 'coder', 'claude', 't', 't')"
            )
            await db.execute(
                "INSERT INTO sessions (session_id, agent_id, task, started_at) "
                "VALUES ('s1', 'a1', 'do work', 't')"
            )
            await db.execute("PRAGMA user_version = 2")
            await db.commit()

        await HiveStore(db_path).initialize()  # runs migration 3

        async with aiosqlite.connect(db_path) as db:
            version = (await (await db.execute("PRAGMA user_version")).fetchone())[0]
            cursor = await db.execute("PRAGMA table_info(sessions)")
            cols = {row[1] for row in await cursor.fetchall()}
            cursor = await db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='approvals'"
            )
            approvals_exists = await cursor.fetchone() is not None
            cursor = await db.execute("SELECT task FROM sessions WHERE session_id = 's1'")
            session_row = await cursor.fetchone()

        assert version == LATEST_SCHEMA_VERSION
        assert {"user_id", "session_key", "created_at", "last_active", "metadata"} <= cols
        assert approvals_exists
        assert session_row is not None and session_row[0] == "do work"  # data survived

    @pytest.mark.asyncio
    async def test_approval_lifecycle(self, tmp_path: Path) -> None:
        """create -> find_active(pending) -> resolve(approved) -> consume."""
        store = HiveStore(tmp_path / "state.db")
        await store.initialize()
        await store.create_approval("ap1", "a1", "shell_exec", '{"cmd": "ls"}', "h1")

        pending = await store.get_pending_approvals("a1")
        assert len(pending) == 1 and pending[0]["approval_id"] == "ap1"

        active = await store.find_active_approval("a1", "shell_exec", "h1")
        assert active is not None and active["status"] == "pending"

        assert await store.resolve_approval("ap1", "approved", resolved_by="user") is True
        # Double-resolution is a no-op (rowcount guard).
        assert await store.resolve_approval("ap1", "denied", resolved_by="user") is False

        active = await store.find_active_approval("a1", "shell_exec", "h1")
        assert active is not None and active["status"] == "approved"

        assert await store.consume_approval("ap1") is True
        # Consumed approvals no longer match, so a re-call would re-prompt.
        assert await store.find_active_approval("a1", "shell_exec", "h1") is None

    @pytest.mark.asyncio
    async def test_session_resolution(self, tmp_path: Path) -> None:
        store = HiveStore(tmp_path / "state.db")
        await store.initialize()
        await store.create_session("s1", "a1", "task", user_id="alice", session_key="chat-1")

        resolved = await store.resolve_session("alice", "chat-1")
        assert resolved is not None and resolved["session_id"] == "s1"
        assert await store.resolve_session("bob", "chat-1") is None
        assert [s["session_id"] for s in await store.list_sessions(user_id="alice")] == ["s1"]


class TestConcurrencySettings:
    @pytest.mark.asyncio
    async def test_wal_mode_enabled_persistently(self, tmp_path: Path) -> None:
        """initialize() switches the DB to WAL, which sticks for new connections."""
        db_path = tmp_path / "state.db"
        await HiveStore(db_path).initialize()

        # A brand-new connection (no PRAGMA) should report WAL -- it's persistent.
        async with aiosqlite.connect(db_path) as db:
            mode = (await (await db.execute("PRAGMA journal_mode")).fetchone())[0]
        assert mode.lower() == "wal"

    @pytest.mark.asyncio
    async def test_concurrent_writers_no_lock_errors(self, tmp_path: Path) -> None:
        """Many concurrent writes under WAL + busy_timeout complete without errors."""
        import asyncio

        store = HiveStore(tmp_path / "state.db")
        await store.initialize()

        async def writer(i: int) -> None:
            await store.save_nudge(f"n-{i}", f"agent-{i % 4}", f"msg {i}")

        await asyncio.gather(*(writer(i) for i in range(40)))
        # No exception == no "database is locked". Spot-check a couple landed.
        assert await store.get_pending_nudges("agent-0")

    @pytest.mark.asyncio
    async def test_get_pending_nudges_only_marks_returned(self, tmp_path: Path) -> None:
        """A nudge added after a read isn't marked delivered, so it isn't lost."""
        store = HiveStore(tmp_path / "state.db")
        await store.initialize()
        await store.save_nudge("n1", "a1", "first")
        await store.save_nudge("n2", "a1", "second")

        first = await store.get_pending_nudges("a1")
        assert sorted(first) == ["first", "second"]

        # A nudge that arrives later must still be delivered exactly once.
        await store.save_nudge("n3", "a1", "third")
        assert await store.get_pending_nudges("a1") == ["third"]
        assert await store.get_pending_nudges("a1") == []

    @pytest.mark.asyncio
    async def test_get_pending_nudges_survives_concurrent_insert(self, tmp_path: Path) -> None:
        """A nudge committed by another connection *between* the SELECT and the
        UPDATE must not be marked delivered. This is the actual race the by-id
        UPDATE fixes -- the old `WHERE delivered = 0` sweep would have lost it."""
        from contextlib import asynccontextmanager

        db_path = tmp_path / "state.db"
        store = HiveStore(db_path)
        await store.initialize()
        await store.save_nudge("n1", "a1", "first")

        real_connect = store._connect
        state = {"injected": False}

        @asynccontextmanager
        async def connect_with_injection(foreign_keys: bool = False):  # type: ignore[no-untyped-def]
            async with real_connect(foreign_keys=foreign_keys) as db:
                real_execute = db.execute

                # Sync wrapper preserves aiosqlite's `await`/`async with` duality.
                # Just before the UPDATE runs (rows already SELECTed), a *separate*
                # connection commits a new nudge -- the exact race window where the
                # old `WHERE delivered = 0` sweep would have marked it delivered.
                def execute(*args, **kwargs):  # type: ignore[no-untyped-def]
                    sql = args[0] if args else kwargs.get("sql", "")
                    if (
                        not state["injected"]
                        and sql.lstrip().upper().startswith("UPDATE")
                        and "nudges" in sql
                    ):
                        state["injected"] = True

                        async def _inject_then_update():  # type: ignore[no-untyped-def]
                            async with aiosqlite.connect(db_path) as other:
                                await other.execute(
                                    "INSERT INTO nudges (nudge_id, agent_id, message, "
                                    "delivered, created_at) VALUES ('n2','a1','second',0,'t')"
                                )
                                await other.commit()
                            return await real_execute(*args, **kwargs)

                        return _inject_then_update()
                    return real_execute(*args, **kwargs)

                db.execute = execute  # type: ignore[method-assign]
                yield db

        store._connect = connect_with_injection  # type: ignore[assignment,method-assign]
        returned = await store.get_pending_nudges("a1")
        store._connect = real_connect  # type: ignore[method-assign]

        assert returned == ["first"]
        # n2 raced in mid-call; it must survive as still-pending, not be lost.
        assert await store.get_pending_nudges("a1") == ["second"]


class TestCascades:
    @pytest.mark.asyncio
    async def test_delete_agent_cascades_to_children(self, tmp_path: Path) -> None:
        """delete_agent removes the agent and (via cascade) all its child rows."""
        db_path = tmp_path / "state.db"
        store = HiveStore(db_path)
        await store.initialize()
        await _insert_agent_with_children(db_path)

        assert await store.delete_agent("a1") is True

        async with aiosqlite.connect(db_path) as db:
            for table in ("agents", "goals", "tasks"):
                cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
                assert (await cur.fetchone())[0] == 0, f"{table} not cascaded"

    @pytest.mark.asyncio
    async def test_delete_missing_agent_returns_false(self, tmp_path: Path) -> None:
        store = HiveStore(tmp_path / "state.db")
        await store.initialize()
        assert await store.delete_agent("nope") is False

    @pytest.mark.asyncio
    async def test_v1_to_v2_migration_adds_cascade_and_keeps_data(self, tmp_path: Path) -> None:
        """A v1 DB (no cascade) upgrades to v2 with data intact and cascade live."""
        db_path = tmp_path / "state.db"
        async with aiosqlite.connect(db_path) as db:
            await db.executescript(_V1_SCHEMA_NO_CASCADE)
            await db.execute("PRAGMA user_version = 1")
            await db.commit()
        await _insert_agent_with_children(db_path)

        store = HiveStore(db_path)
        await store.initialize()  # runs migration 2 (table rebuild)

        async with aiosqlite.connect(db_path) as db:
            version = (await (await db.execute("PRAGMA user_version")).fetchone())[0]
            # Data survived the rebuild.
            cur = await db.execute("SELECT objective FROM goals WHERE goal_id = 'g1'")
            goal_row = await cur.fetchone()
            cur = await db.execute("SELECT description FROM tasks WHERE task_id = 't1'")
            task_row = await cur.fetchone()

        assert version == LATEST_SCHEMA_VERSION
        assert goal_row is not None and goal_row[0] == "obj"
        assert task_row is not None and task_row[0] == "desc"

        # Cascade is now active: deleting the agent clears the rebuilt children.
        assert await store.delete_agent("a1") is True
        async with aiosqlite.connect(db_path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM goals")
            assert (await cur.fetchone())[0] == 0

    @pytest.mark.asyncio
    async def test_migration_recovers_from_mid_swap_crash(self, tmp_path: Path) -> None:
        """Crash after DROP {table} but before RENAME must not lose data on re-run.

        Simulates that window for `goals`: the table is gone and `goals_new`
        holds the only copy. A re-run must finish the swap, not drop the data.
        """
        db_path = tmp_path / "state.db"
        store = HiveStore(db_path)
        await store.initialize()  # fresh v2
        await _insert_agent_with_children(db_path)

        # Reproduce the interrupted-swap on-disk state: goals -> goals_new, v1.
        async with aiosqlite.connect(db_path) as db:
            await db.execute("ALTER TABLE goals RENAME TO goals_new")
            await db.execute("PRAGMA user_version = 1")
            await db.commit()

        await HiveStore(db_path).initialize()  # must recover, not destroy

        async with aiosqlite.connect(db_path) as db:
            version = (await (await db.execute("PRAGMA user_version")).fetchone())[0]
            cur = await db.execute("SELECT objective FROM goals WHERE goal_id = 'g1'")
            row = await cur.fetchone()
            # The leftover *_new table is gone after a clean run.
            cur = await db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='goals_new'"
            )
            leftover = await cur.fetchone()

        assert version == LATEST_SCHEMA_VERSION
        assert row is not None and row[0] == "obj"  # data recovered, not lost
        assert leftover is None
