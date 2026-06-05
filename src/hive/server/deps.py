"""Server context (dependency-injection container) and request-scoped services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from fastapi import Request

from hive.agents.state import AgentState
from hive.config import HiveConfig
from hive.errors import AgentNotFoundError
from hive.memory.store import HiveStore

if TYPE_CHECKING:
    from hive.daemon.loop import HiveDaemon

# Header carrying the tenant identity. Local-first default is a single shared user.
USER_HEADER = "X-Hive-User"
DEFAULT_USER = "default"


async def resolve_agent_id(store: HiveStore, name_or_id: str) -> str:
    """Resolve an agent name, full id, or id-prefix to a full agent_id.

    Mirrors ``Hive._resolve_agent`` but async (no thread-pool hop in the request
    path). Raises ``AgentNotFoundError`` (mapped to 404 by the error handlers).
    """
    agents: list[AgentState] = await store.list_agents()
    for a in agents:
        if a.agent_id == name_or_id:
            return a.agent_id
    for a in agents:
        if a.name == name_or_id:
            return a.agent_id
    for a in agents:
        if a.agent_id.startswith(name_or_id):
            return a.agent_id
    raise AgentNotFoundError(f"Agent not found: {name_or_id}")


class SessionService:
    """Resolves and creates per-user/per-session rows for tenant isolation."""

    def __init__(self, store: HiveStore):
        self._store = store

    async def resolve(
        self,
        user_id: str,
        agent_id: str,
        task: str,
        session_id: str | None = None,
        session_key: str | None = None,
    ) -> str:
        """Return a session_id for this request, creating one if needed.

        Order: explicit ``session_id`` (tenant-checked) -> ``(user_id, session_key)``
        -> a fresh anonymous session scoped to ``user_id``.
        """
        if session_id is not None:
            existing = await self._store.get_session(session_id)
            if existing is None or (existing.get("user_id") or DEFAULT_USER) != user_id:
                raise AgentNotFoundError(f"Session not found: {session_id}")
            await self._store.touch_session(session_id)
            return session_id

        if session_key is not None:
            found = await self._store.resolve_session(user_id, session_key)
            if found is not None:
                await self._store.touch_session(found["session_id"])
                return str(found["session_id"])

        new_id = f"sess-{uuid4().hex[:12]}"
        await self._store.create_session(
            new_id, agent_id, task, user_id=user_id, session_key=session_key
        )
        return new_id


@dataclass
class ServerContext:
    """Long-lived, shared state built once in the app lifespan.

    The HTTP layer mutates the same ``hive.db`` the daemon reads (WAL handles the
    concurrent writers), so the server is useful both standalone (a separate
    ``hive start`` drives agents) and with an in-process daemon (``--with-daemon``).
    """

    root: Path
    hive_dir: Path
    store: HiveStore
    config: HiveConfig
    sessions: SessionService
    daemon: HiveDaemon | None = None


def get_context(request: Request) -> ServerContext:
    """FastAPI dependency: the ServerContext stored on app state."""
    return request.app.state.ctx  # type: ignore[no-any-return]


def get_user(request: Request) -> str:
    """FastAPI dependency: the calling tenant from the user header."""
    return request.headers.get(USER_HEADER) or DEFAULT_USER


def agent_state_to_summary(a: AgentState, goal: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "agent_id": a.agent_id,
        "name": a.name,
        "role": a.role,
        "model": a.model,
        "status": a.status.value,
        "goal": goal["objective"] if goal else None,
    }
