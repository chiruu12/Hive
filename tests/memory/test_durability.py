"""Tests for migration v4, delegation persistence, and the retention janitor."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite
import pytest

from hive.agents.delegation import DelegationEngine
from hive.agents.state import AgentState, AgentStatus
from hive.memory.store import LATEST_SCHEMA_VERSION, HiveStore


async def _seed_agent(store: HiveStore, agent_id: str, status: AgentStatus) -> AgentState:
    state = AgentState(
        agent_id=agent_id,
        name=agent_id.split("-")[0],
        role="test",
        model="mock-model",
        status=status,
        workspace=".",
    )
    await store.save_agent(state)
    return state


class TestMigration4:
    @pytest.mark.asyncio
    async def test_fresh_db_is_v4_with_delegations(self, tmp_path: Path) -> None:
        store = HiveStore(tmp_path / "hive.db")
        await store.initialize()
        async with aiosqlite.connect(tmp_path / "hive.db") as db:
            version = (await (await db.execute("PRAGMA user_version")).fetchone())[0]
            tables = {
                r[0]
                for r in await (
                    await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                ).fetchall()
            }
        assert version == LATEST_SCHEMA_VERSION == 4
        assert "delegations" in tables

    @pytest.mark.asyncio
    async def test_backfills_null_session_timestamps(self, tmp_path: Path) -> None:
        db_path = tmp_path / "hive.db"
        store = HiveStore(db_path)
        await store.initialize()
        # Simulate a pre-v4 row: timestamps NULLed, version rolled back to 3.
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """INSERT INTO sessions
                   (session_id, agent_id, task, status, started_at, completed_at)
                   VALUES ('s-old', 'a1', 't', 'completed', '2026-01-01T00:00:00',
                           '2026-01-02T00:00:00')"""
            )
            await db.execute(
                "UPDATE sessions SET created_at = NULL, last_active = NULL "
                "WHERE session_id = 's-old'"
            )
            await db.execute("PRAGMA user_version = 3")
            await db.commit()

        await HiveStore(db_path).initialize()

        async with aiosqlite.connect(db_path) as db:
            row = await (
                await db.execute(
                    "SELECT created_at, last_active FROM sessions WHERE session_id = 's-old'"
                )
            ).fetchone()
        assert row[0] == "2026-01-01T00:00:00"
        assert row[1] == "2026-01-02T00:00:00"


class TestDelegationPersistence:
    @pytest.mark.asyncio
    async def test_delegation_survives_engine_restart(self, tmp_path: Path) -> None:
        store = HiveStore(tmp_path / "hive.db")
        await store.initialize()
        await _seed_agent(store, "boss-0001", AgentStatus.IDLE)
        await _seed_agent(store, "worker-0001", AgentStatus.IDLE)

        engine = DelegationEngine(store)
        rec = await engine.delegate("boss-0001", "worker-0001", "do the thing")

        # A fresh engine (simulated daemon restart) sees the delegation.
        fresh = DelegationEngine(store)
        outbound = await fresh.list_outbound("boss-0001")
        assert [r.delegation_id for r in outbound] == [rec.delegation_id]
        inbound = await fresh.list_inbound("worker-0001")
        assert [r.delegation_id for r in inbound] == [rec.delegation_id]

        found = await fresh.check_completion(rec.delegation_id)
        assert found is not None
        assert found.goal_id == rec.goal_id

    @pytest.mark.asyncio
    async def test_completion_status_persisted(self, tmp_path: Path) -> None:
        store = HiveStore(tmp_path / "hive.db")
        await store.initialize()
        await _seed_agent(store, "boss-0001", AgentStatus.IDLE)
        await _seed_agent(store, "worker-0001", AgentStatus.IDLE)

        engine = DelegationEngine(store)
        rec = await engine.delegate("boss-0001", "worker-0001", "do the thing")
        await store.complete_goal(rec.goal_id)

        # A fresh engine resolves completion from the store and writes it back.
        fresh = DelegationEngine(store)
        checked = await fresh.check_completion(rec.delegation_id)
        assert checked is not None and checked.status == "completed"

        row = await store.get_delegation(rec.delegation_id)
        assert row is not None and row["status"] == "completed"


class TestRetentionJanitor:
    @pytest.mark.asyncio
    async def test_cleanup_removes_old_terminal_rows_only(self, tmp_path: Path) -> None:
        db_path = tmp_path / "hive.db"
        store = HiveStore(db_path)
        await store.initialize()
        await _seed_agent(store, "alive-0001", AgentStatus.IDLE)

        old = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """INSERT INTO approvals
                   (approval_id, agent_id, tool_name, arguments, status, created_at)
                   VALUES ('ap-old', 'alive-0001', 't', '{}', 'denied', ?),
                          ('ap-pending', 'alive-0001', 't', '{}', 'pending', ?)""",
                (old, old),
            )
            await db.execute(
                """INSERT INTO nudges (nudge_id, agent_id, message, delivered, created_at)
                   VALUES ('n-old', 'alive-0001', 'm', 1, ?),
                          ('n-new', 'alive-0001', 'm', 0, ?)""",
                (old, old),
            )
            await db.commit()

        counts = await store.cleanup(days=30)
        assert counts["approvals"] == 1
        assert counts["nudges"] == 1

        async with aiosqlite.connect(db_path) as db:
            approvals = {
                r[0]
                for r in await (await db.execute("SELECT approval_id FROM approvals")).fetchall()
            }
            nudges = {
                r[0] for r in await (await db.execute("SELECT nudge_id FROM nudges")).fetchall()
            }
        # Pending approval and undelivered nudge survive, no matter how old.
        assert approvals == {"ap-pending"}
        assert nudges == {"n-new"}

    @pytest.mark.asyncio
    async def test_cleanup_denies_dead_agents_pending_approvals(self, tmp_path: Path) -> None:
        db_path = tmp_path / "hive.db"
        store = HiveStore(db_path)
        await store.initialize()
        await _seed_agent(store, "dead-0001", AgentStatus.DEAD)
        await _seed_agent(store, "alive-0001", AgentStatus.IDLE)

        now = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """INSERT INTO approvals
                   (approval_id, agent_id, tool_name, arguments, status, created_at)
                   VALUES ('ap-dead', 'dead-0001', 't', '{}', 'pending', ?),
                          ('ap-alive', 'alive-0001', 't', '{}', 'pending', ?)""",
                (now, now),
            )
            await db.commit()

        counts = await store.cleanup(days=30)
        assert counts["dead_agent_approvals"] == 1

        dead = await store.get_delegation("nope")  # unrelated miss returns None
        assert dead is None
        async with aiosqlite.connect(db_path) as db:
            rows = dict(
                await (await db.execute("SELECT approval_id, status FROM approvals")).fetchall()
            )
        assert rows["ap-dead"] == "denied"
        assert rows["ap-alive"] == "pending"
