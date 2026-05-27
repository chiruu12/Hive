"""SQLite persistence for hive state."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from hive.agents.state import AgentState, AgentStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
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

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    task TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL,
    completed_at TEXT,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);

CREATE TABLE IF NOT EXISTS goals (
    goal_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    objective TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    priority INTEGER DEFAULT 4,
    parent_goal_id TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    steps_completed INTEGER DEFAULT 0,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);

CREATE TABLE IF NOT EXISTS nudges (
    nudge_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    message TEXT NOT NULL,
    delivered INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);

CREATE TABLE IF NOT EXISTS schedules (
    schedule_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    objective TEXT NOT NULL,
    every_n_cycles INTEGER NOT NULL,
    last_fired_cycle INTEGER DEFAULT 0,
    enabled INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);

CREATE TABLE IF NOT EXISTS sub_agents (
    sub_agent_id TEXT PRIMARY KEY,
    parent_agent_id TEXT NOT NULL,
    task TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    result TEXT DEFAULT '',
    depth INTEGER DEFAULT 1,
    max_cycles INTEGER DEFAULT 10,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (parent_agent_id) REFERENCES agents(agent_id)
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    description TEXT NOT NULL,
    priority TEXT DEFAULT 'medium',
    status TEXT DEFAULT 'pending',
    due_date TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);

CREATE TABLE IF NOT EXISTS alarms (
    alarm_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    description TEXT NOT NULL,
    fire_at TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);
"""


class HiveStore:
    """Async SQLite store for hive agent and session state."""

    def __init__(self, db_path: Path):
        self._db_path = db_path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_SCHEMA)
            cursor = await db.execute("PRAGMA table_info(goals)")
            columns = {row[1] for row in await cursor.fetchall()}
            if "parent_goal_id" not in columns:
                await db.execute(
                    "ALTER TABLE goals ADD COLUMN parent_goal_id TEXT",
                )
            cursor = await db.execute("PRAGMA table_info(agents)")
            agent_cols = {row[1] for row in await cursor.fetchall()}
            if "spawned_by" not in agent_cols:
                await db.execute("ALTER TABLE agents ADD COLUMN spawned_by TEXT")
            if "max_cycles" not in agent_cols:
                await db.execute("ALTER TABLE agents ADD COLUMN max_cycles INTEGER")
            if "cycles_lived" not in agent_cols:
                await db.execute("ALTER TABLE agents ADD COLUMN cycles_lived INTEGER DEFAULT 0")
            await db.commit()

    async def save_agent(self, state: AgentState) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO agents
                   (agent_id, name, role, model, status, current_task,
                    steps_completed, steps_total, workspace, spawned_at,
                    last_active, error, spawned_by, max_cycles, cycles_lived)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    state.agent_id,
                    state.name,
                    state.role,
                    state.model,
                    state.status.value,
                    state.current_task,
                    state.steps_completed,
                    state.steps_total,
                    state.workspace,
                    state.spawned_at.isoformat(),
                    state.last_active.isoformat(),
                    state.error,
                    state.spawned_by,
                    state.max_cycles,
                    state.cycles_lived,
                ),
            )
            await db.commit()

    async def get_agent(self, agent_id: str) -> AgentState | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                return self._row_to_state(row)

    async def list_agents(self) -> list[AgentState]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM agents ORDER BY spawned_at DESC") as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_state(row) for row in rows]

    async def update_agent_status(
        self, agent_id: str, status: AgentStatus, error: str | None = None
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """UPDATE agents SET status = ?, error = ?, last_active = ?
                   WHERE agent_id = ?""",
                (status.value, error, datetime.now(UTC).isoformat(), agent_id),
            )
            await db.commit()

    async def save_session(
        self,
        session_id: str,
        agent_id: str,
        task: str,
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO sessions
                   (session_id, agent_id, task, status, started_at)
                   VALUES (?, ?, ?, 'running', ?)""",
                (session_id, agent_id, task, datetime.now(UTC).isoformat()),
            )
            await db.commit()

    async def complete_session(
        self,
        session_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        duration_ms: int = 0,
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """UPDATE sessions
                   SET status = 'completed', completed_at = ?,
                       input_tokens = ?, output_tokens = ?, duration_ms = ?
                   WHERE session_id = ?""",
                (
                    datetime.now(UTC).isoformat(),
                    input_tokens,
                    output_tokens,
                    duration_ms,
                    session_id,
                ),
            )
            await db.commit()

    async def save_goal(
        self,
        goal_id: str,
        agent_id: str,
        objective: str,
        priority: int = 4,
        parent_goal_id: str | None = None,
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO goals
                   (goal_id, agent_id, objective, status, priority,
                    parent_goal_id, created_at)
                   VALUES (?, ?, ?, 'active', ?, ?, ?)""",
                (
                    goal_id,
                    agent_id,
                    objective,
                    priority,
                    parent_goal_id,
                    datetime.now(UTC).isoformat(),
                ),
            )
            await db.commit()

    async def get_active_goal(self, agent_id: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM goals WHERE agent_id = ? AND status = 'active' LIMIT 1",
                (agent_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_goal_by_id(self, goal_id: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM goals WHERE goal_id = ?", (goal_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_subgoals(
        self,
        parent_goal_id: str,
    ) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM goals WHERE parent_goal_id = ? ORDER BY priority DESC",
                (parent_goal_id,),
            ) as cursor:
                return [dict(row) async for row in cursor]

    async def complete_goal(self, goal_id: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE goals SET status = 'completed', completed_at = ? WHERE goal_id = ?",
                (datetime.now(UTC).isoformat(), goal_id),
            )
            await db.commit()

    async def update_goal_progress(self, goal_id: str, steps_done: int, steps_failed: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE goals SET steps_completed = ? WHERE goal_id = ?",
                (steps_done, goal_id),
            )
            await db.commit()

    async def abandon_goal(self, goal_id: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE goals SET status = 'abandoned', completed_at = ? WHERE goal_id = ?",
                (datetime.now(UTC).isoformat(), goal_id),
            )
            await db.commit()

    async def list_agent_goals(self, agent_id: str, limit: int = 10) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM goals WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?",
                (agent_id, limit),
            ) as cursor:
                return [dict(row) async for row in cursor]

    async def save_nudge(self, nudge_id: str, agent_id: str, message: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO nudges (nudge_id, agent_id, message, created_at) VALUES (?, ?, ?, ?)",
                (nudge_id, agent_id, message, datetime.now(UTC).isoformat()),
            )
            await db.commit()

    async def get_pending_nudges(self, agent_id: str) -> list[str]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT message FROM nudges WHERE agent_id = ? AND delivered = 0",
                (agent_id,),
            ) as cursor:
                messages = [row["message"] async for row in cursor]
            await db.execute(
                "UPDATE nudges SET delivered = 1 WHERE agent_id = ? AND delivered = 0",
                (agent_id,),
            )
            await db.commit()
            return messages

    async def save_schedule(
        self,
        schedule_id: str,
        agent_id: str,
        objective: str,
        every_n_cycles: int,
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT INTO schedules
                   (schedule_id, agent_id, objective, every_n_cycles, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    schedule_id,
                    agent_id,
                    objective,
                    every_n_cycles,
                    datetime.now(UTC).isoformat(),
                ),
            )
            await db.commit()

    async def list_schedules(self, agent_id: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM schedules WHERE agent_id = ? AND enabled = 1",
                (agent_id,),
            ) as cursor:
                return [dict(row) async for row in cursor]

    async def get_due_schedules(self, agent_id: str, current_cycle: int) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM schedules
                   WHERE agent_id = ? AND enabled = 1
                   AND (? - last_fired_cycle) >= every_n_cycles""",
                (agent_id, current_cycle),
            ) as cursor:
                return [dict(row) async for row in cursor]

    async def fire_schedule(self, schedule_id: str, cycle: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE schedules SET last_fired_cycle = ? WHERE schedule_id = ?",
                (cycle, schedule_id),
            )
            await db.commit()

    async def disable_schedule(self, schedule_id: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE schedules SET enabled = 0 WHERE schedule_id = ?",
                (schedule_id,),
            )
            await db.commit()

    async def save_sub_agent(
        self,
        sub_agent_id: str,
        parent_agent_id: str,
        task: str,
        depth: int = 1,
        max_cycles: int = 10,
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT INTO sub_agents
                   (sub_agent_id, parent_agent_id, task, status, depth,
                    max_cycles, created_at)
                   VALUES (?, ?, ?, 'running', ?, ?, ?)""",
                (
                    sub_agent_id,
                    parent_agent_id,
                    task,
                    depth,
                    max_cycles,
                    datetime.now(UTC).isoformat(),
                ),
            )
            await db.commit()

    async def list_sub_agents(self, parent_agent_id: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM sub_agents WHERE parent_agent_id = ?",
                (parent_agent_id,),
            ) as cursor:
                return [dict(row) async for row in cursor]

    async def get_sub_agent(self, sub_agent_id: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM sub_agents WHERE sub_agent_id = ?",
                (sub_agent_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def complete_sub_agent(self, sub_agent_id: str, result: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """UPDATE sub_agents
                   SET status = 'completed', result = ?, completed_at = ?
                   WHERE sub_agent_id = ?""",
                (result, datetime.now(UTC).isoformat(), sub_agent_id),
            )
            await db.commit()

    async def increment_cycles(self, agent_id: str) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE agents SET cycles_lived = cycles_lived + 1 WHERE agent_id = ?",
                (agent_id,),
            )
            await db.commit()
            async with db.execute(
                "SELECT cycles_lived FROM agents WHERE agent_id = ?",
                (agent_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    # --- Tasks ---

    async def save_task(
        self,
        task_id: str,
        agent_id: str,
        description: str,
        priority: str = "medium",
        due_date: str | None = None,
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT INTO tasks
                   (task_id, agent_id, description, priority, due_date, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    agent_id,
                    description,
                    priority,
                    due_date,
                    datetime.now(UTC).isoformat(),
                ),
            )
            await db.commit()

    async def list_tasks(
        self, agent_id: str, status: str = "pending", priority: str | None = None
    ) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            if priority:
                async with db.execute(
                    "SELECT * FROM tasks WHERE agent_id = ? AND status = ? AND priority = ? "
                    "ORDER BY created_at DESC",
                    (agent_id, status, priority),
                ) as cursor:
                    return [dict(row) for row in await cursor.fetchall()]
            async with db.execute(
                "SELECT * FROM tasks WHERE agent_id = ? AND status = ? ORDER BY created_at DESC",
                (agent_id, status),
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def complete_task(self, task_id: str) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """UPDATE tasks SET status = 'done', completed_at = ?
                   WHERE task_id = ? AND status = 'pending'""",
                (datetime.now(UTC).isoformat(), task_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def uncomplete_task(self, task_id: str) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """UPDATE tasks SET status = 'pending', completed_at = NULL
                   WHERE task_id = ? AND status = 'done'""",
                (task_id,),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def delete_task(self, task_id: str) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def update_task(
        self,
        task_id: str,
        description: str | None = None,
        priority: str | None = None,
        due_date: str | None = None,
    ) -> bool:
        fields: list[str] = []
        values: list[Any] = []
        if description is not None:
            fields.append("description = ?")
            values.append(description)
        if priority is not None:
            fields.append("priority = ?")
            values.append(priority)
        if due_date is not None:
            fields.append("due_date = ?")
            values.append(due_date if due_date else None)
        if not fields:
            return False
        values.append(task_id)
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                f"UPDATE tasks SET {', '.join(fields)} WHERE task_id = ?",
                tuple(values),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def list_all_tasks(
        self, status: str = "pending", priority: str | None = None
    ) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            if priority:
                async with db.execute(
                    "SELECT * FROM tasks WHERE status = ? AND priority = ? "
                    "ORDER BY created_at DESC",
                    (status, priority),
                ) as cursor:
                    return [dict(row) for row in await cursor.fetchall()]
            async with db.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    # --- Alarms ---

    async def save_alarm(
        self, alarm_id: str, agent_id: str, description: str, fire_at: str
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT INTO alarms (alarm_id, agent_id, description, fire_at, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (alarm_id, agent_id, description, fire_at, datetime.now(UTC).isoformat()),
            )
            await db.commit()

    async def list_pending_alarms(self, agent_id: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM alarms WHERE agent_id = ? AND status = 'pending' ORDER BY fire_at",
                (agent_id,),
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def get_due_alarms(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM alarms WHERE status = 'pending' AND fire_at <= ?",
                (datetime.now(UTC).isoformat(),),
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def mark_alarm_fired(self, alarm_id: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE alarms SET status = 'fired' WHERE alarm_id = ?",
                (alarm_id,),
            )
            await db.commit()

    async def cancel_alarm(self, alarm_id: str) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM alarms WHERE alarm_id = ? AND status = 'pending'",
                (alarm_id,),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def list_all_pending_alarms(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM alarms WHERE status = 'pending' ORDER BY fire_at",
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    def _row_to_state(self, row: aiosqlite.Row) -> AgentState:
        return AgentState(
            agent_id=row["agent_id"],
            name=row["name"],
            role=row["role"],
            model=row["model"],
            status=AgentStatus(row["status"]),
            current_task=row["current_task"],
            steps_completed=row["steps_completed"],
            steps_total=row["steps_total"],
            workspace=row["workspace"],
            spawned_at=datetime.fromisoformat(row["spawned_at"]),
            last_active=datetime.fromisoformat(row["last_active"]),
            error=row["error"],
            spawned_by=row["spawned_by"] if "spawned_by" in row.keys() else None,
            max_cycles=row["max_cycles"] if "max_cycles" in row.keys() else None,
            cycles_lived=row["cycles_lived"] if "cycles_lived" in row.keys() else 0,
        )
