"""In-memory :class:`StoreProtocol` fake for unit tests."""

from __future__ import annotations

from typing import Any

from hive.agents.state import AgentState, AgentStatus
from hive.memory.protocol import StoreProtocol


class MinimalStore:
    """Lightweight in-memory store implementing :class:`StoreProtocol`."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentState] = {}
        self._goals: dict[str, dict[str, Any]] = {}
        self._nudges: list[dict[str, Any]] = []
        self._approvals: dict[str, dict[str, Any]] = {}
        self._sessions: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, dict[str, Any]] = {}
        self._schedules: dict[str, dict[str, Any]] = {}
        self._alarms: dict[str, dict[str, Any]] = {}
        self._delegations: dict[str, dict[str, Any]] = {}
        self._sub_agents: dict[str, dict[str, Any]] = {}

    async def initialize(self) -> None:
        return None

    async def save_agent(self, state: AgentState) -> None:
        self._agents[state.agent_id] = state

    async def get_agent(self, agent_id: str) -> AgentState | None:
        return self._agents.get(agent_id)

    async def list_agents(self, limit: int | None = None, offset: int = 0) -> list[AgentState]:
        agents = list(self._agents.values())
        if limit is None:
            return agents[offset:]
        return agents[offset : offset + limit]

    async def update_agent_status(
        self, agent_id: str, status: AgentStatus, error: str | None = None
    ) -> None:
        agent = self._agents.get(agent_id)
        if agent is not None:
            agent.status = status

    async def increment_cycles(self, agent_id: str) -> int:
        agent = self._agents.get(agent_id)
        if agent is None:
            return 0
        agent.cycles_alive += 1
        return agent.cycles_alive

    async def save_goal(
        self,
        goal_id: str,
        agent_id: str,
        objective: str,
        priority: int = 4,
        parent_goal_id: str | None = None,
    ) -> None:
        self._goals[goal_id] = {
            "goal_id": goal_id,
            "agent_id": agent_id,
            "objective": objective,
            "priority": priority,
            "parent_goal_id": parent_goal_id,
            "status": "in_progress",
            "steps_done": 0,
            "steps_failed": 0,
        }

    async def get_active_goal(self, agent_id: str) -> dict[str, Any] | None:
        for goal in self._goals.values():
            if goal["agent_id"] == agent_id and goal.get("status") == "in_progress":
                return goal
        return None

    async def get_active_goals_map(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for goal in self._goals.values():
            if goal.get("status") == "in_progress":
                result[str(goal["agent_id"])] = str(goal["objective"])
        return result

    async def get_goal_by_id(self, goal_id: str) -> dict[str, Any] | None:
        return self._goals.get(goal_id)

    async def complete_goal(self, goal_id: str) -> None:
        if goal_id in self._goals:
            self._goals[goal_id]["status"] = "completed"

    async def abandon_goal(self, goal_id: str) -> None:
        if goal_id in self._goals:
            self._goals[goal_id]["status"] = "abandoned"

    async def update_goal_progress(self, goal_id: str, steps_done: int, steps_failed: int) -> None:
        if goal_id in self._goals:
            self._goals[goal_id]["steps_done"] = steps_done
            self._goals[goal_id]["steps_failed"] = steps_failed

    async def list_agent_goals(self, agent_id: str, limit: int = 10) -> list[dict[str, Any]]:
        goals = [g for g in self._goals.values() if g["agent_id"] == agent_id]
        return goals[:limit]

    async def get_subgoals(self, parent_goal_id: str) -> list[dict[str, Any]]:
        return [g for g in self._goals.values() if g.get("parent_goal_id") == parent_goal_id]

    async def save_nudge(self, nudge_id: str, agent_id: str, message: str) -> None:
        self._nudges.append(
            {
                "nudge_id": nudge_id,
                "agent_id": agent_id,
                "message": message,
                "delivered": False,
            }
        )

    async def get_pending_nudges(self, agent_id: str) -> list[str]:
        pending = [
            n["message"] for n in self._nudges if n["agent_id"] == agent_id and not n["delivered"]
        ]
        for n in self._nudges:
            if n["agent_id"] == agent_id and not n["delivered"]:
                n["delivered"] = True
        return pending

    async def find_active_approval(
        self, agent_id: str, tool_name: str, args_hash: str
    ) -> dict[str, Any] | None:
        for row in self._approvals.values():
            if (
                row.get("agent_id") == agent_id
                and row.get("tool_name") == tool_name
                and row.get("args_hash") == args_hash
                and row.get("status") == "pending"
            ):
                return row
        return None

    async def create_approval(
        self,
        approval_id: str,
        agent_id: str,
        tool_name: str,
        arguments: str,
        args_hash: str,
        session_id: str | None = None,
        goal_id: str | None = None,
        cycle_created: int | None = None,
    ) -> None:
        self._approvals[approval_id] = {
            "approval_id": approval_id,
            "agent_id": agent_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "args_hash": args_hash,
            "session_id": session_id,
            "goal_id": goal_id,
            "cycle_created": cycle_created,
            "status": "pending",
        }

    async def consume_approval(self, approval_id: str) -> bool:
        row = self._approvals.get(approval_id)
        if row is None or row.get("status") != "pending":
            return False
        row["status"] = "consumed"
        return True

    async def get_pending_approvals(
        self, agent_id: str, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        rows = [
            r
            for r in self._approvals.values()
            if r.get("agent_id") == agent_id and r.get("status") == "pending"
        ]
        if limit is None:
            return rows[offset:]
        return rows[offset : offset + limit]

    async def resolve_approval(
        self,
        approval_id: str,
        status: str,
        resolved_by: str | None = None,
        reason: str | None = None,
        agent_id: str | None = None,
    ) -> bool:
        row = self._approvals.get(approval_id)
        if row is None:
            return False
        row["status"] = status
        return True

    async def expire_approvals(self, agent_id: str, before_created_at: str) -> int:
        return 0

    async def create_session(
        self,
        session_id: str,
        agent_id: str,
        task: str,
        user_id: str = "default",
        session_key: str | None = None,
        metadata: str | None = None,
    ) -> None:
        self._sessions[session_id] = {
            "session_id": session_id,
            "agent_id": agent_id,
            "task": task,
            "user_id": user_id,
            "session_key": session_key,
            "metadata": metadata,
            "status": "running",
        }

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        return self._sessions.get(session_id)

    async def touch_session(self, session_id: str) -> None:
        return None

    async def resolve_session(self, user_id: str, session_key: str) -> dict[str, Any] | None:
        for row in self._sessions.values():
            if row.get("user_id") == user_id and row.get("session_key") == session_key:
                return row
        return None

    async def list_sessions(
        self,
        user_id: str | None = None,
        agent_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = list(self._sessions.values())
        if user_id is not None:
            rows = [r for r in rows if r.get("user_id") == user_id]
        if agent_id is not None:
            rows = [r for r in rows if r.get("agent_id") == agent_id]
        if limit is None:
            return rows[offset:]
        return rows[offset : offset + limit]

    async def complete_session(
        self,
        session_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        duration_ms: int = 0,
    ) -> None:
        if session_id in self._sessions:
            self._sessions[session_id]["status"] = "completed"

    async def save_task(
        self,
        task_id: str,
        agent_id: str,
        description: str,
        priority: str = "medium",
        due_date: str | None = None,
    ) -> None:
        self._tasks[task_id] = {
            "task_id": task_id,
            "agent_id": agent_id,
            "description": description,
            "priority": priority,
            "due_date": due_date,
            "status": "pending",
        }

    async def list_tasks(
        self, agent_id: str, status: str = "pending", priority: str | None = None
    ) -> list[dict[str, Any]]:
        rows = [
            t
            for t in self._tasks.values()
            if t["agent_id"] == agent_id and t.get("status") == status
        ]
        if priority is not None:
            rows = [t for t in rows if t.get("priority") == priority]
        return rows

    async def list_all_tasks(
        self, status: str = "pending", priority: str | None = None
    ) -> list[dict[str, Any]]:
        rows = [t for t in self._tasks.values() if t.get("status") == status]
        if priority is not None:
            rows = [t for t in rows if t.get("priority") == priority]
        return rows

    async def complete_task(self, task_id: str) -> bool:
        if task_id not in self._tasks:
            return False
        self._tasks[task_id]["status"] = "completed"
        return True

    async def uncomplete_task(self, task_id: str) -> bool:
        if task_id not in self._tasks:
            return False
        self._tasks[task_id]["status"] = "pending"
        return True

    async def delete_task(self, task_id: str) -> bool:
        return self._tasks.pop(task_id, None) is not None

    async def update_task(
        self,
        task_id: str,
        description: str | None = None,
        priority: str | None = None,
        due_date: str | None = None,
    ) -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if description is not None:
            task["description"] = description
        if priority is not None:
            task["priority"] = priority
        if due_date is not None:
            task["due_date"] = due_date
        return True

    async def save_schedule(
        self,
        schedule_id: str,
        agent_id: str,
        objective: str,
        every_n_cycles: int,
    ) -> None:
        self._schedules[schedule_id] = {
            "schedule_id": schedule_id,
            "agent_id": agent_id,
            "objective": objective,
            "every_n_cycles": every_n_cycles,
            "enabled": True,
        }

    async def list_schedules(self, agent_id: str) -> list[dict[str, Any]]:
        return [s for s in self._schedules.values() if s["agent_id"] == agent_id and s["enabled"]]

    async def disable_schedule(self, schedule_id: str, agent_id: str) -> bool:
        sched = self._schedules.get(schedule_id)
        if sched is None or sched["agent_id"] != agent_id:
            return False
        sched["enabled"] = False
        return True

    async def get_due_schedules(self, agent_id: str, current_cycle: int) -> list[dict[str, Any]]:
        return []

    async def fire_schedule(self, schedule_id: str, cycle: int) -> None:
        return None

    async def save_alarm(
        self, alarm_id: str, agent_id: str, description: str, fire_at: str
    ) -> None:
        self._alarms[alarm_id] = {
            "alarm_id": alarm_id,
            "agent_id": agent_id,
            "description": description,
            "fire_at": fire_at,
            "fired": False,
        }

    async def get_due_alarms(self) -> list[dict[str, Any]]:
        return [a for a in self._alarms.values() if not a["fired"]]

    async def mark_alarm_fired(self, alarm_id: str) -> None:
        if alarm_id in self._alarms:
            self._alarms[alarm_id]["fired"] = True

    async def list_pending_alarms(self, agent_id: str) -> list[dict[str, Any]]:
        return [a for a in self._alarms.values() if a["agent_id"] == agent_id and not a["fired"]]

    async def list_all_pending_alarms(self) -> list[dict[str, Any]]:
        return [a for a in self._alarms.values() if not a["fired"]]

    async def cancel_alarm(self, alarm_id: str) -> bool:
        if alarm_id not in self._alarms:
            return False
        self._alarms[alarm_id]["fired"] = True
        return True

    async def save_delegation(
        self,
        delegation_id: str,
        from_agent: str,
        to_agent: str,
        task: str,
        goal_id: str = "",
    ) -> None:
        self._delegations[delegation_id] = {
            "delegation_id": delegation_id,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "task": task,
            "goal_id": goal_id,
            "status": "pending",
        }

    async def get_delegation(self, delegation_id: str) -> dict[str, Any] | None:
        return self._delegations.get(delegation_id)

    async def update_delegation_status(
        self, delegation_id: str, status: str, result: str = ""
    ) -> None:
        if delegation_id in self._delegations:
            self._delegations[delegation_id]["status"] = status
            self._delegations[delegation_id]["result"] = result

    async def list_delegations(
        self, from_agent: str | None = None, to_agent: str | None = None
    ) -> list[dict[str, Any]]:
        rows = list(self._delegations.values())
        if from_agent is not None:
            rows = [r for r in rows if r.get("from_agent") == from_agent]
        if to_agent is not None:
            rows = [r for r in rows if r.get("to_agent") == to_agent]
        return rows

    async def save_sub_agent(
        self,
        sub_agent_id: str,
        parent_agent_id: str,
        task: str,
        depth: int = 1,
        max_cycles: int = 10,
    ) -> None:
        self._sub_agents[sub_agent_id] = {
            "sub_agent_id": sub_agent_id,
            "parent_agent_id": parent_agent_id,
            "task": task,
            "depth": depth,
            "max_cycles": max_cycles,
            "status": "active",
        }

    async def get_sub_agent(self, sub_agent_id: str) -> dict[str, Any] | None:
        return self._sub_agents.get(sub_agent_id)

    async def list_sub_agents(self, parent_agent_id: str) -> list[dict[str, Any]]:
        return [
            s
            for s in self._sub_agents.values()
            if s["parent_agent_id"] == parent_agent_id and s.get("status") == "active"
        ]

    async def complete_sub_agent(self, sub_agent_id: str, result: str) -> None:
        if sub_agent_id in self._sub_agents:
            self._sub_agents[sub_agent_id]["status"] = "completed"
            self._sub_agents[sub_agent_id]["result"] = result

    async def cleanup(self, days: int = 30, session_ttl_hours: int = 0) -> dict[str, int]:
        return {}


def assert_store_protocol(store: object) -> None:
    """Raise ``AssertionError`` if *store* does not satisfy :class:`StoreProtocol`."""
    if not isinstance(store, StoreProtocol):
        raise AssertionError(f"{type(store).__name__} does not satisfy StoreProtocol")
