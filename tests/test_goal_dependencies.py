"""Tests for goal dependencies — parent/subtask relationships and rollup."""

from __future__ import annotations

from pathlib import Path

import pytest

from hive.memory.goals import GoalEngine
from hive.memory.store import HiveStore


@pytest.fixture
async def store(tmp_path: Path) -> HiveStore:
    s = HiveStore(tmp_path / "test.db")
    await s.initialize()
    return s


@pytest.fixture
def engine(store: HiveStore) -> GoalEngine:
    return GoalEngine(store)


class TestSaveGoalWithParent:
    @pytest.mark.asyncio
    async def test_save_with_parent(self, store: HiveStore) -> None:
        await store.save_goal("parent-1", "agent-a", "Big task")
        await store.save_goal(
            "child-1",
            "agent-a",
            "Sub task",
            parent_goal_id="parent-1",
        )
        child = await store.get_goal_by_id("child-1")
        assert child is not None
        assert child["parent_goal_id"] == "parent-1"

    @pytest.mark.asyncio
    async def test_save_without_parent(self, store: HiveStore) -> None:
        await store.save_goal("solo-1", "agent-a", "Standalone")
        goal = await store.get_goal_by_id("solo-1")
        assert goal is not None
        assert goal["parent_goal_id"] is None


class TestGetSubgoals:
    @pytest.mark.asyncio
    async def test_returns_children(self, store: HiveStore) -> None:
        await store.save_goal("p-1", "agent-a", "Parent")
        await store.save_goal(
            "c-1",
            "agent-a",
            "Child 1",
            parent_goal_id="p-1",
        )
        await store.save_goal(
            "c-2",
            "agent-a",
            "Child 2",
            parent_goal_id="p-1",
        )
        subs = await store.get_subgoals("p-1")
        assert len(subs) == 2
        objectives = {s["objective"] for s in subs}
        assert objectives == {"Child 1", "Child 2"}

    @pytest.mark.asyncio
    async def test_no_children(self, store: HiveStore) -> None:
        await store.save_goal("lonely", "agent-a", "No kids")
        subs = await store.get_subgoals("lonely")
        assert subs == []


class TestGetGoalById:
    @pytest.mark.asyncio
    async def test_found(self, store: HiveStore) -> None:
        await store.save_goal("find-me", "agent-a", "Here I am")
        result = await store.get_goal_by_id("find-me")
        assert result is not None
        assert result["objective"] == "Here I am"

    @pytest.mark.asyncio
    async def test_not_found(self, store: HiveStore) -> None:
        result = await store.get_goal_by_id("nonexistent")
        assert result is None


class TestGoalEngineCreate:
    @pytest.mark.asyncio
    async def test_create_with_parent(self, engine: GoalEngine) -> None:
        parent = await engine.create("agent-a", "Big project", priority=8)
        child = await engine.create(
            "agent-a",
            "Step 1",
            priority=6,
            parent_id=parent.goal_id,
        )
        assert child.parent_goal_id == parent.goal_id

        stored = await engine._store.get_goal_by_id(child.goal_id)
        assert stored is not None
        assert stored["parent_goal_id"] == parent.goal_id


class TestSubtaskRollup:
    @pytest.mark.asyncio
    async def test_all_completed_rolls_up(
        self,
        engine: GoalEngine,
        store: HiveStore,
    ) -> None:
        parent = await engine.create("agent-a", "Main goal")
        c1 = await engine.create(
            "agent-a",
            "Sub 1",
            parent_id=parent.goal_id,
        )
        c2 = await engine.create(
            "agent-a",
            "Sub 2",
            parent_id=parent.goal_id,
        )
        await store.complete_goal(c1.goal_id)
        await store.complete_goal(c2.goal_id)

        result = await engine.check_subtask_rollup(parent.goal_id)
        assert result == "completed"

    @pytest.mark.asyncio
    async def test_one_abandoned_rolls_up(
        self,
        engine: GoalEngine,
        store: HiveStore,
    ) -> None:
        parent = await engine.create("agent-a", "Main goal")
        c1 = await engine.create(
            "agent-a",
            "Sub 1",
            parent_id=parent.goal_id,
        )
        c2 = await engine.create(
            "agent-a",
            "Sub 2",
            parent_id=parent.goal_id,
        )
        await store.complete_goal(c1.goal_id)
        await store.abandon_goal(c2.goal_id)

        result = await engine.check_subtask_rollup(parent.goal_id)
        assert result == "abandoned"

    @pytest.mark.asyncio
    async def test_still_active_no_rollup(
        self,
        engine: GoalEngine,
        store: HiveStore,
    ) -> None:
        parent = await engine.create("agent-a", "Main goal")
        await engine.create(
            "agent-a",
            "Sub 1",
            parent_id=parent.goal_id,
        )
        c2 = await engine.create(
            "agent-a",
            "Sub 2",
            parent_id=parent.goal_id,
        )
        await store.complete_goal(c2.goal_id)

        result = await engine.check_subtask_rollup(parent.goal_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_subtasks_no_rollup(
        self,
        engine: GoalEngine,
    ) -> None:
        parent = await engine.create("agent-a", "Leaf goal")
        result = await engine.check_subtask_rollup(parent.goal_id)
        assert result is None


class TestSchemaMigration:
    @pytest.mark.asyncio
    async def test_migrate_adds_column(self, tmp_path: Path) -> None:
        """Existing DB without parent_goal_id gets migrated."""
        import aiosqlite

        db_path = tmp_path / "legacy.db"
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                CREATE TABLE goals (
                    goal_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    priority INTEGER DEFAULT 4,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    steps_completed INTEGER DEFAULT 0
                )
            """)
            await db.execute(
                "INSERT INTO goals (goal_id, agent_id, objective, created_at)"
                " VALUES ('old-1', 'a1', 'legacy goal', '2025-01-01')",
            )
            await db.commit()

        store = HiveStore(db_path)
        await store.initialize()

        await store.save_goal(
            "new-1",
            "a1",
            "new goal",
            parent_goal_id="old-1",
        )
        goal = await store.get_goal_by_id("new-1")
        assert goal is not None
        assert goal["parent_goal_id"] == "old-1"
