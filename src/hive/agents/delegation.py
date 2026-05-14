"""Delegation engine — route subtasks between agents."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from hive.memory.store import HiveStore


class DelegationRecord(BaseModel):
    delegation_id: str
    from_agent: str
    to_agent: str
    task: str
    goal_id: str = ""
    status: str = "pending"
    result: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class DelegationEngine:
    """Manages task delegation between agents."""

    def __init__(self, store: HiveStore):
        self._store = store
        self._active: dict[str, DelegationRecord] = {}

    async def delegate(
        self,
        from_agent: str,
        to_agent: str,
        task: str,
    ) -> DelegationRecord:
        """Create a goal in another agent's name and track it."""
        did = f"del-{uuid4().hex[:8]}"
        goal_id = f"goal-{uuid4().hex[:8]}"

        await self._store.save_goal(goal_id, to_agent, task, priority=8)

        record = DelegationRecord(
            delegation_id=did,
            from_agent=from_agent,
            to_agent=to_agent,
            task=task,
            goal_id=goal_id,
        )
        self._active[did] = record
        return record

    async def check_completion(self, delegation_id: str) -> DelegationRecord | None:
        """Check if a delegated task has been completed."""
        rec = self._active.get(delegation_id)
        if not rec:
            return None

        goal = await self._store.get_active_goal(rec.to_agent)
        if goal and goal.get("goal_id") == rec.goal_id:
            return rec

        goals = await self._store.list_agent_goals(rec.to_agent, limit=20)
        for g in goals:
            if g.get("goal_id") == rec.goal_id:
                if g.get("status") == "completed":
                    rec.status = "completed"
                    rec.result = f"Goal completed by {rec.to_agent}"
                    rec.completed_at = datetime.now(UTC)
                elif g.get("status") == "abandoned":
                    rec.status = "failed"
                    rec.result = f"Goal abandoned by {rec.to_agent}"
                    rec.completed_at = datetime.now(UTC)
                break

        return rec

    async def list_outbound(self, agent_id: str) -> list[DelegationRecord]:
        return [r for r in self._active.values() if r.from_agent == agent_id]

    async def list_inbound(self, agent_id: str) -> list[DelegationRecord]:
        return [r for r in self._active.values() if r.to_agent == agent_id]

    def find_best_agent(
        self, task: str, agents: list[str], specializations: dict[str, dict[str, Any]]
    ) -> str | None:
        """Pick the best agent for a task based on specialization scores."""
        if not agents:
            return None

        best_agent = None
        best_score = -1.0

        for aid in agents:
            spec = specializations.get(aid, {})
            score = spec.get("overall_score", 0.5)
            if score > best_score:
                best_score = score
                best_agent = aid

        return best_agent
