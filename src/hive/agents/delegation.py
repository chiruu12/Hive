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
    """Manages task delegation between agents.

    Records are persisted in the store so delegated work survives a daemon
    restart; ``_active`` is an in-process cache over those rows.
    """

    def __init__(
        self,
        store: HiveStore,
        a2a_store: Any | None = None,
    ):
        self._store = store
        self._a2a_store = a2a_store
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
        await self._store.save_delegation(did, from_agent, to_agent, task, goal_id)

        if self._a2a_store:
            from hive.interactions.a2a import A2AMessage, A2AMessageType

            msg = A2AMessage(
                type=A2AMessageType.DELEGATE,
                from_agent=from_agent,
                to_agent=to_agent,
                subject=f"Delegation: {task[:60]}",
                body=task,
                expects_reply=True,
                metadata={
                    "delegation_id": did,
                    "goal_id": goal_id,
                },
            )
            await self._a2a_store.send(msg)

        return record

    async def check_completion(self, delegation_id: str) -> DelegationRecord | None:
        """Check if a delegated task has been completed."""
        rec = self._active.get(delegation_id)
        if not rec:
            # Cache miss (e.g. after a daemon restart): rehydrate from the store.
            row = await self._store.get_delegation(delegation_id)
            if not row:
                return None
            rec = self._record_from_row(row)
            self._active[delegation_id] = rec

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
                if rec.status != "pending":
                    await self._store.update_delegation_status(
                        rec.delegation_id, rec.status, rec.result
                    )
                break

        return rec

    async def list_outbound(self, agent_id: str) -> list[DelegationRecord]:
        rows = await self._store.list_delegations(from_agent=agent_id)
        return [self._active.get(r["delegation_id"]) or self._record_from_row(r) for r in rows]

    async def list_inbound(self, agent_id: str) -> list[DelegationRecord]:
        rows = await self._store.list_delegations(to_agent=agent_id)
        return [self._active.get(r["delegation_id"]) or self._record_from_row(r) for r in rows]

    @staticmethod
    def _record_from_row(row: dict[str, Any]) -> DelegationRecord:
        return DelegationRecord(
            delegation_id=row["delegation_id"],
            from_agent=row["from_agent"],
            to_agent=row["to_agent"],
            task=row["task"],
            goal_id=row.get("goal_id") or "",
            status=row.get("status") or "pending",
            result=row.get("result") or "",
            created_at=datetime.fromisoformat(row["created_at"]),
            completed_at=(
                datetime.fromisoformat(row["completed_at"]) if row.get("completed_at") else None
            ),
        )

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
