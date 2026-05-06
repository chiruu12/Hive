"""SQLite persistence for hive state."""

from datetime import UTC, datetime
from pathlib import Path

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
"""


class HiveStore:
    """Async SQLite store for hive agent and session state."""

    def __init__(self, db_path: Path):
        self._db_path = db_path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()

    async def save_agent(self, state: AgentState) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO agents
                   (agent_id, name, role, model, status, current_task,
                    steps_completed, steps_total, workspace, spawned_at, last_active, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        self, goal_id: str, agent_id: str, objective: str, priority: int = 4
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO goals
                   (goal_id, agent_id, objective, status, priority, created_at)
                   VALUES (?, ?, ?, 'active', ?, ?)""",
                (goal_id, agent_id, objective, priority, datetime.now(UTC).isoformat()),
            )
            await db.commit()

    async def get_active_goal(self, agent_id: str) -> dict | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM goals WHERE agent_id = ? AND status = 'active' LIMIT 1",
                (agent_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def complete_goal(self, goal_id: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE goals SET status = 'completed', completed_at = ? WHERE goal_id = ?",
                (datetime.now(UTC).isoformat(), goal_id),
            )
            await db.commit()

    async def abandon_goal(self, goal_id: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE goals SET status = 'abandoned', completed_at = ? WHERE goal_id = ?",
                (datetime.now(UTC).isoformat(), goal_id),
            )
            await db.commit()

    async def list_agent_goals(self, agent_id: str, limit: int = 10) -> list[dict]:
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
        )
