"""Base class for agent decision loops."""

import json
import logging
from abc import ABC
from typing import Any

from hive.agents.profile import AgentProfile
from hive.execution.context import ExecutionContext
from hive.logging.writer import LogWriter
from hive.memory.events import EventLog, EventType, HiveEvent
from hive.memory.store import HiveStore

logger = logging.getLogger(__name__)


class AgentLoopBase(ABC):
    """Shared foundation for AgentLoop and ExistenceLoop."""

    def __init__(
        self,
        agent_id: str,
        profile: AgentProfile,
        provider: Any,
        ctx: ExecutionContext,
        store: HiveStore,
        event_log: EventLog,
        log_writer: LogWriter | None = None,
        session_id: str = "",
    ):
        self._agent_id = agent_id
        self._profile = profile
        self._provider = provider
        self._ctx = ctx
        self._store = store
        self._events = event_log
        self._log = log_writer
        self._session_id = session_id or f"sess-{agent_id}"

    async def _emit(self, event_type: EventType, data: dict) -> None:
        event = HiveEvent(
            event_type=event_type,
            agent_id=self._agent_id,
            session_id=self._session_id,
            data=data,
        )
        await self._events.append(event)

    @staticmethod
    def _parse_json(text: str) -> dict | None:
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON: %s", text[:200])
            return None
