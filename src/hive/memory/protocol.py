"""Protocol for the persistence store — enables test doubles and alternative backends.

Defines the minimal interface that consumers of :class:`HiveStore` actually
depend on.  The concrete ``HiveStore`` already implements all of these methods;
this protocol formalises the contract so that:

* High-level modules can type-hint against ``StoreProtocol`` instead of the
  concrete class (Dependency Inversion).
* Tests can provide lightweight fakes without touching SQLite.
* A future alternative backend (e.g. PostgreSQL) can be swapped in.

Signatures here must mirror ``HiveStore`` exactly (including parameter names
and defaults) — mypy's structural checks reject the concrete class otherwise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from hive.agents.state import AgentState, AgentStatus


@runtime_checkable
class StoreProtocol(Protocol):
    """Minimal persistence contract used across the Hive codebase.

    Only the methods that are actually called by daemon, server, CLI, tools,
    and agents are listed here.  A grep audit (2026-07-22, stability-02)
    confirmed every entry is referenced; see ``tests/fakes/minimal_store.py``
    for a test double.  ``HiveStore`` implements all of them (and many more)
    — this protocol is a *view* of the surface area consumers depend on,
    not an exhaustive listing of every ``HiveStore`` helper.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create tables / run migrations.  Idempotent."""
        ...

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    async def save_agent(self, state: AgentState) -> None:
        """Insert or update an agent row."""
        ...

    async def get_agent(self, agent_id: str) -> AgentState | None:
        """Return an ``AgentState`` or ``None``."""
        ...

    async def list_agents(self, limit: int | None = None, offset: int = 0) -> list[AgentState]:
        """Return all agents (optionally paginated)."""
        ...

    async def update_agent_status(
        self, agent_id: str, status: AgentStatus, error: str | None = None
    ) -> None:
        """Set the agent's current status."""
        ...

    async def increment_cycles(self, agent_id: str) -> int:
        """Bump the agent's ``cycles_alive`` counter.  Returns the new count."""
        ...

    # ------------------------------------------------------------------
    # Goals
    # ------------------------------------------------------------------

    async def save_goal(
        self,
        goal_id: str,
        agent_id: str,
        objective: str,
        priority: int = 4,
        parent_goal_id: str | None = None,
    ) -> None:
        """Persist a new goal."""
        ...

    async def get_active_goal(self, agent_id: str) -> dict[str, Any] | None:
        """Return the agent's current in-progress goal, or ``None``."""
        ...

    async def get_active_goals_map(self) -> dict[str, str]:
        """Batch: return ``{agent_id: objective}`` for agents with active goals."""
        ...

    async def get_goal_by_id(self, goal_id: str) -> dict[str, Any] | None:
        """Look up a goal by its primary key."""
        ...

    async def complete_goal(self, goal_id: str) -> None:
        """Mark a goal as completed."""
        ...

    async def abandon_goal(self, goal_id: str) -> None:
        """Mark a goal as abandoned."""
        ...

    async def update_goal_progress(self, goal_id: str, steps_done: int, steps_failed: int) -> None:
        """Update step counters on a goal."""
        ...

    async def list_agent_goals(self, agent_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent goals for an agent."""
        ...

    async def get_subgoals(self, parent_goal_id: str) -> list[dict[str, Any]]:
        """Return child goals of a parent."""
        ...

    # ------------------------------------------------------------------
    # Nudges
    # ------------------------------------------------------------------

    async def save_nudge(self, nudge_id: str, agent_id: str, message: str) -> None:
        """Persist a nudge."""
        ...

    async def get_pending_nudges(self, agent_id: str) -> list[str]:
        """Return undelivered nudge messages for an agent."""
        ...

    # ------------------------------------------------------------------
    # Approvals
    # ------------------------------------------------------------------

    async def find_active_approval(
        self, agent_id: str, tool_name: str, args_hash: str
    ) -> dict[str, Any] | None:
        """Find a pending approval matching the tool + args."""
        ...

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
        """Create a new pending approval."""
        ...

    async def consume_approval(self, approval_id: str) -> bool:
        """Mark an approval as consumed.  Returns success flag."""
        ...

    async def get_pending_approvals(
        self, agent_id: str, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Return pending approvals for an agent."""
        ...

    async def resolve_approval(
        self,
        approval_id: str,
        status: str,
        resolved_by: str | None = None,
        reason: str | None = None,
        agent_id: str | None = None,
    ) -> bool:
        """Approve or deny.  Returns success flag."""
        ...

    async def expire_approvals(self, agent_id: str, before_created_at: str) -> int:
        """Expire stale approvals.  Returns the number expired."""
        ...

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    async def create_session(
        self,
        session_id: str,
        agent_id: str,
        task: str,
        user_id: str = "default",
        session_key: str | None = None,
        metadata: str | None = None,
    ) -> None:
        """Create a new session."""
        ...

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Look up a session by id."""
        ...

    async def touch_session(self, session_id: str) -> None:
        """Update ``last_active`` timestamp."""
        ...

    async def resolve_session(self, user_id: str, session_key: str) -> dict[str, Any] | None:
        """Find a session by user_id + session_key."""
        ...

    async def list_sessions(
        self,
        user_id: str | None = None,
        agent_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List sessions (optionally filtered/paginated)."""
        ...

    async def complete_session(
        self,
        session_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        duration_ms: int = 0,
    ) -> None:
        """Mark a session as completed."""
        ...

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    async def save_task(
        self,
        task_id: str,
        agent_id: str,
        description: str,
        priority: str = "medium",
        due_date: str | None = None,
    ) -> None:
        """Create a task."""
        ...

    async def list_tasks(
        self, agent_id: str, status: str = "pending", priority: str | None = None
    ) -> list[dict[str, Any]]:
        """List tasks for an agent."""
        ...

    async def list_all_tasks(
        self, status: str = "pending", priority: str | None = None
    ) -> list[dict[str, Any]]:
        """List tasks across all agents."""
        ...

    async def complete_task(self, task_id: str) -> bool:
        """Mark a task as done."""
        ...

    async def uncomplete_task(self, task_id: str) -> bool:
        """Revert a task to pending."""
        ...

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        ...

    async def update_task(
        self,
        task_id: str,
        description: str | None = None,
        priority: str | None = None,
        due_date: str | None = None,
    ) -> bool:
        """Update task fields."""
        ...

    # ------------------------------------------------------------------
    # Schedules
    # ------------------------------------------------------------------

    async def save_schedule(
        self,
        schedule_id: str,
        agent_id: str,
        objective: str,
        every_n_cycles: int,
    ) -> None:
        """Create a recurring schedule."""
        ...

    async def list_schedules(self, agent_id: str) -> list[dict[str, Any]]:
        """List active schedules for an agent."""
        ...

    async def disable_schedule(self, schedule_id: str, agent_id: str) -> bool:
        """Disable a schedule owned by ``agent_id``. Returns True if a row was updated."""
        ...

    async def get_due_schedules(self, agent_id: str, current_cycle: int) -> list[dict[str, Any]]:
        """Return schedules due for firing."""
        ...

    async def fire_schedule(self, schedule_id: str, cycle: int) -> None:
        """Update ``last_fired`` on a schedule."""
        ...

    # ------------------------------------------------------------------
    # Alarms
    # ------------------------------------------------------------------

    async def save_alarm(
        self, alarm_id: str, agent_id: str, description: str, fire_at: str
    ) -> None:
        """Create an alarm."""
        ...

    async def get_due_alarms(self) -> list[dict[str, Any]]:
        """Return all alarms whose ``fire_at`` has passed."""
        ...

    async def mark_alarm_fired(self, alarm_id: str) -> None:
        """Mark an alarm as fired."""
        ...

    async def list_pending_alarms(self, agent_id: str) -> list[dict[str, Any]]:
        """Return unfired alarms for an agent."""
        ...

    async def list_all_pending_alarms(self) -> list[dict[str, Any]]:
        """Return all unfired alarms."""
        ...

    async def cancel_alarm(self, alarm_id: str) -> bool:
        """Cancel an alarm."""
        ...

    # ------------------------------------------------------------------
    # Delegations
    # ------------------------------------------------------------------

    async def save_delegation(
        self,
        delegation_id: str,
        from_agent: str,
        to_agent: str,
        task: str,
        goal_id: str = "",
    ) -> None:
        """Record a delegation."""
        ...

    async def get_delegation(self, delegation_id: str) -> dict[str, Any] | None:
        """Look up a delegation by id."""
        ...

    async def update_delegation_status(
        self, delegation_id: str, status: str, result: str = ""
    ) -> None:
        """Update delegation outcome."""
        ...

    async def list_delegations(
        self, from_agent: str | None = None, to_agent: str | None = None
    ) -> list[dict[str, Any]]:
        """List delegations (by from_agent or to_agent)."""
        ...

    # ------------------------------------------------------------------
    # Sub-agents
    # ------------------------------------------------------------------

    async def save_sub_agent(
        self,
        sub_agent_id: str,
        parent_agent_id: str,
        task: str,
        depth: int = 1,
        max_cycles: int = 10,
    ) -> None:
        """Record a sub-agent relationship."""
        ...

    async def get_sub_agent(self, sub_agent_id: str) -> dict[str, Any] | None:
        """Look up a sub-agent."""
        ...

    async def list_sub_agents(self, parent_agent_id: str) -> list[dict[str, Any]]:
        """List sub-agents of a parent."""
        ...

    async def complete_sub_agent(self, sub_agent_id: str, result: str) -> None:
        """Mark a sub-agent as completed."""
        ...

    # ------------------------------------------------------------------
    # Retention
    # ------------------------------------------------------------------

    async def cleanup(self, days: int = 30, session_ttl_hours: int = 0) -> dict[str, int]:
        """Run the retention janitor.  Returns counts of deleted rows."""
        ...
