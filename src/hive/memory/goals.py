"""Persistent goal engine — hierarchy, priority, and lifecycle tracking."""

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from hive.memory.store import HiveStore


class GoalRecord(BaseModel):
    goal_id: str
    agent_id: str
    objective: str
    priority: int = 4
    status: str = "active"
    parent_goal_id: str | None = None
    subgoal_ids: list[str] = []
    steps_completed: int = 0
    steps_failed: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    last_worked_on: datetime | None = None


class GoalEngine:
    """Manages goal lifecycle with hierarchy and priority scheduling."""

    def __init__(self, store: HiveStore):
        self._store = store

    async def create(
        self,
        agent_id: str,
        objective: str,
        priority: int = 4,
        parent_id: str | None = None,
    ) -> GoalRecord:
        goal_id = f"goal-{uuid4().hex[:8]}"
        await self._store.save_goal(goal_id, agent_id, objective, priority)

        if parent_id:
            parent = await self._get_record(parent_id)
            if parent and goal_id not in parent.get("subgoal_ids", []):
                subs = parent.get("subgoal_ids", [])
                subs.append(goal_id)

        return GoalRecord(
            goal_id=goal_id,
            agent_id=agent_id,
            objective=objective,
            priority=priority,
            parent_goal_id=parent_id,
        )

    async def get_active(self, agent_id: str) -> GoalRecord | None:
        row = await self._store.get_active_goal(agent_id)
        if not row:
            return None
        return self._row_to_record(row)

    async def select_next(self, agent_id: str) -> GoalRecord | None:
        """Pick the highest-priority active goal, preferring recently worked ones."""
        goals = await self._store.list_agent_goals(agent_id, limit=20)
        active = [g for g in goals if g.get("status") == "active"]
        if not active:
            return None
        active.sort(
            key=lambda g: (
                -g.get("priority", 4),
                g.get("created_at", ""),
            )
        )
        return self._row_to_record(active[0])

    async def decompose(self, goal_id: str, sub_objectives: list[str]) -> list[GoalRecord]:
        parent = await self._get_record(goal_id)
        if not parent:
            return []
        agent_id = parent["agent_id"]
        children = []
        for obj in sub_objectives:
            child = await self.create(agent_id, obj, parent.get("priority", 4), goal_id)
            children.append(child)
        return children

    async def update_progress(self, goal_id: str, steps_done: int, steps_failed: int) -> None:
        goal = await self._get_record(goal_id)
        if not goal:
            return
        await self._store.update_goal_progress(goal_id, steps_done, steps_failed)

    async def complete(self, goal_id: str) -> None:
        await self._store.complete_goal(goal_id)

    async def abandon(self, goal_id: str, reason: str = "") -> None:
        await self._store.abandon_goal(goal_id)

    async def list_history(self, agent_id: str, limit: int = 10) -> list[GoalRecord]:
        rows = await self._store.list_agent_goals(agent_id, limit)
        return [self._row_to_record(r) for r in rows]

    async def count_completed(self, agent_id: str) -> int:
        goals = await self._store.list_agent_goals(agent_id, limit=100)
        return sum(1 for g in goals if g.get("status") == "completed")

    async def count_abandoned(self, agent_id: str) -> int:
        goals = await self._store.list_agent_goals(agent_id, limit=100)
        return sum(1 for g in goals if g.get("status") == "abandoned")

    async def _get_record(self, goal_id: str) -> dict | None:
        goals = await self._store.list_agent_goals("", limit=1000)
        for g in goals:
            if g.get("goal_id") == goal_id:
                return g
        return None

    @staticmethod
    def _row_to_record(row: dict) -> GoalRecord:
        return GoalRecord(
            goal_id=row["goal_id"],
            agent_id=row["agent_id"],
            objective=row["objective"],
            priority=row.get("priority", 4),
            status=row.get("status", "active"),
            steps_completed=row.get("steps_completed", 0),
            steps_failed=row.get("steps_failed", 0),
            created_at=datetime.fromisoformat(row["created_at"])
            if isinstance(row.get("created_at"), str)
            else row.get("created_at", datetime.now(UTC)),
            completed_at=datetime.fromisoformat(row["completed_at"])
            if isinstance(row.get("completed_at"), str) and row.get("completed_at")
            else None,
        )
