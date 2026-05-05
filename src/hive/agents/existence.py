"""Existence loop — autonomous goal generation when agent is idle."""

import json
import logging
from uuid import uuid4

from hive.agents.profile import AgentProfile
from hive.agents.suffering import SufferingState
from hive.execution.registry import ToolRegistry
from hive.memory.events import EventLog, EventType, HiveEvent
from hive.memory.store import HiveStore
from hive.models.claude import ClaudeCLIProvider

logger = logging.getLogger(__name__)


class ExistenceLoop:
    """Generates autonomous goals from agent context when idle."""

    def __init__(
        self,
        agent_id: str,
        profile: AgentProfile,
        provider: ClaudeCLIProvider,
        registry: ToolRegistry,
        store: HiveStore,
        event_log: EventLog,
        session_id: str = "",
    ):
        self._agent_id = agent_id
        self._profile = profile
        self._provider = provider
        self._registry = registry
        self._store = store
        self._events = event_log
        self._session_id = session_id or f"sess-{agent_id}"

    async def generate_goal(
        self,
        suffering: SufferingState,
        peer_summaries: list[str],
        nudges: list[str],
    ) -> str | None:
        """Build context and ask Claude what the agent should do next."""
        recent_goals = await self._store.list_agent_goals(self._agent_id, limit=5)
        tools_desc = self._registry.get_tool_schemas()

        prompt = self._build_prompt(suffering, peer_summaries, recent_goals, tools_desc, nudges)

        response = await self._provider.complete(
            messages=[{"role": "user", "content": prompt}],
            system=self._profile.build_system_prompt(),
        )

        goal_text = self._parse_goal(response.content)
        if not goal_text:
            return None

        goal_id = f"goal-{uuid4().hex[:8]}"
        await self._store.save_goal(goal_id, self._agent_id, goal_text)

        await self._emit(
            EventType.GOAL_SET,
            {
                "goal_id": goal_id,
                "objective": goal_text,
            },
        )

        return goal_text

    def _build_prompt(
        self,
        suffering: SufferingState,
        peers: list[str],
        recent_goals: list[dict],
        tools_desc: str,
        nudges: list[str],
    ) -> str:
        sections = [
            f"You are {self._profile.name}, a {self._profile.role}.",
        ]

        suffering_frag = suffering.prompt_fragment()
        if suffering_frag:
            sections.append(f"\n--- Your current state ---\n{suffering_frag}")

        if nudges:
            sections.append(
                "\n--- Messages from the user ---\n" + "\n".join(f"• {n}" for n in nudges)
            )

        if recent_goals:
            goal_lines = []
            for g in recent_goals[:5]:
                status = g.get("status", "?")
                obj = g.get("objective", "?")[:80]
                goal_lines.append(f"  [{status}] {obj}")
            sections.append("\n--- Recent goals ---\n" + "\n".join(goal_lines))

        if peers:
            peer_text = "\n".join(f"• {p}" for p in peers)
            sections.append(f"\n--- What others are doing ---\n{peer_text}")

        sections.append(f"\n--- Available tools ---\n{tools_desc}")

        sections.append(
            "\n--- Your task ---\n"
            "What is the single most valuable thing you could do RIGHT NOW?\n"
            "Consider your role, your suffering, what others are doing, "
            "and the tools available.\n\n"
            "Respond with ONLY a JSON object:\n"
            '{"goal": "your chosen goal in one sentence", "reasoning": "why this matters"}\n'
            "No markdown. Just the JSON."
        )

        return "\n".join(sections)

    def _parse_goal(self, text: str) -> str | None:
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        try:
            data = json.loads(text)
            return data.get("goal")
        except json.JSONDecodeError:
            logger.warning("Failed to parse existence response: %s", text[:200])
            return None

    async def _emit(self, event_type: EventType, data: dict) -> None:
        event = HiveEvent(
            event_type=event_type,
            agent_id=self._agent_id,
            session_id=self._session_id,
            data=data,
        )
        await self._events.append(event)
