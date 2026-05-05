"""Agent loop - core execution that drives an agent through a task."""

import logging
import time
from pathlib import Path

from hive.agents.profile import AgentProfile
from hive.agents.state import AgentStatus
from hive.memory.events import EventLog, EventType, HiveEvent
from hive.memory.store import HiveStore
from hive.models._protocol import AssistantMessage, ResultMessage, SystemInit
from hive.models.claude import ClaudeCLIProvider

logger = logging.getLogger(__name__)


class AgentLoop:
    """Drives agent execution by spawning Claude CLI and recording events."""

    def __init__(
        self,
        agent_id: str,
        profile: AgentProfile,
        provider: ClaudeCLIProvider,
        store: HiveStore,
        event_log: EventLog,
    ):
        self._agent_id = agent_id
        self._profile = profile
        self._provider = provider
        self._store = store
        self._events = event_log
        self._session_id = f"sess-{agent_id}"

    async def run(self, task: str, cwd: Path) -> None:
        """Execute a task to completion by spawning Claude and observing."""
        start_time = time.time()

        await self._emit(
            EventType.TASK_STARTED,
            {
                "task": task,
                "profile": self._profile.name,
                "model": self._profile.model,
            },
        )

        await self._store.save_session(self._session_id, self._agent_id, task)
        await self._store.update_agent_status(self._agent_id, AgentStatus.WORKING)

        system_prompt = self._profile.build_system_prompt()
        tools_used = 0

        try:
            async for event in self._provider.run_task(
                task=task,
                system_prompt=system_prompt,
                cwd=str(cwd),
            ):
                if isinstance(event, SystemInit):
                    if event.session_id:
                        self._session_id = event.session_id

                elif isinstance(event, AssistantMessage):
                    for tool_use in event.tool_uses:
                        tools_used += 1
                        await self._emit(
                            EventType.TOOL_USED,
                            {
                                "tool": tool_use.tool_name,
                                "params": tool_use.tool_input or {},
                            },
                        )

                    text = event.text
                    if text.strip():
                        await self._emit(EventType.ASSISTANT_MESSAGE, {"text": text})

                elif isinstance(event, ResultMessage):
                    duration_ms = int((time.time() - start_time) * 1000)
                    await self._emit(
                        EventType.TASK_COMPLETED,
                        {
                            "input_tokens": event.input_tokens or 0,
                            "output_tokens": event.output_tokens or 0,
                            "duration_ms": event.duration_ms or duration_ms,
                            "num_turns": event.num_turns or 0,
                            "tools_used": tools_used,
                        },
                    )

                    await self._store.complete_session(
                        self._session_id,
                        input_tokens=event.input_tokens or 0,
                        output_tokens=event.output_tokens or 0,
                        duration_ms=event.duration_ms or duration_ms,
                    )

            await self._store.update_agent_status(self._agent_id, AgentStatus.IDLE)

        except Exception as e:
            logger.error("Agent %s failed: %s", self._agent_id, e)
            await self._emit(EventType.ERROR, {"message": str(e)})
            await self._store.update_agent_status(self._agent_id, AgentStatus.ERROR, error=str(e))

    async def _emit(self, event_type: EventType, data: dict) -> None:
        event = HiveEvent(
            event_type=event_type,
            agent_id=self._agent_id,
            session_id=self._session_id,
            data=data,
        )
        await self._events.append(event)
