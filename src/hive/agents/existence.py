"""Existence loop — autonomous goal generation when agent is idle."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from hive.agents.profile import AgentProfile
from hive.agents.suffering import SufferingState
from hive.logging.models import DecisionLog, GoalLog
from hive.logging.writer import LogWriter
from hive.memory.events import EventLog, EventType, HiveEvent
from hive.memory.store import HiveStore
from hive.runtime.types import Message

if TYPE_CHECKING:
    from hive.runtime.persona import Persona
    from hive.world.stats import AgentStats

logger = logging.getLogger(__name__)


class ExistenceLoop:
    """Generates autonomous goals from agent context when idle."""

    def __init__(
        self,
        agent_id: str,
        profile: AgentProfile,
        provider: Any,
        store: HiveStore,
        event_log: EventLog,
        hive_dir: Path | None = None,
        log_writer: LogWriter | None = None,
        session_id: str = "",
        economy_enabled: bool = True,
        tools_description: str = "",
        world_status: str = "",
        notepad_content: str = "",
        persona: Persona | None = None,
        stats: AgentStats | None = None,
    ):
        self._agent_id = agent_id
        self._profile = profile
        self._provider = provider
        self._store = store
        self._events = event_log
        self._hive_dir = hive_dir
        self._log = log_writer
        self._session_id = session_id or f"sess-{agent_id}"
        self._economy_enabled = economy_enabled
        self._tools_description = tools_description
        self._world_status = world_status
        self._notepad_content = notepad_content
        self._persona = persona
        self._stats = stats

    async def _emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        event = HiveEvent(
            event_type=event_type,
            agent_id=self._agent_id,
            session_id=self._session_id,
            data=data,
        )
        await self._events.append(event)

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any] | None:
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

    async def generate_goal(
        self,
        suffering: SufferingState,
        peer_summaries: list[str],
        nudges: list[str],
    ) -> str | None:
        """Build context and ask the LLM what the agent should do next."""
        recent_goals = await self._store.list_agent_goals(self._agent_id, limit=5)

        prompt = self._build_prompt(
            suffering, peer_summaries, recent_goals, self._tools_description, nudges
        )

        result = await self._provider.generate_with_metadata(
            messages=[
                Message.system(
                    self._profile.build_system_prompt(economy_enabled=self._economy_enabled)
                ),
                Message.user(prompt),
            ],
        )

        parsed = self._parse_json(result.message.content)
        raw_goal = parsed.get("goal") if parsed else None
        goal_text = str(raw_goal) if raw_goal else None
        reasoning = parsed.get("reasoning") if parsed else None

        if self._log:
            self._log.log_decision(
                DecisionLog(
                    agent_id=self._agent_id,
                    decision_type="existence",
                    model=result.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cost_usd=result.cost_usd,
                    duration_ms=result.duration_ms,
                    response_raw=result.message.content,
                    response_parsed=parsed,
                    success=goal_text is not None,
                )
            )

        if not goal_text:
            return None

        recent_goals = await self._store.list_agent_goals(self._agent_id, limit=5)
        rejection = self._validate_goal(goal_text, recent_goals)
        if rejection:
            logger.info("Goal rejected for %s: %s", self._agent_id, rejection)
            return None

        goal_id = f"goal-{uuid4().hex[:8]}"
        await self._store.save_goal(goal_id, self._agent_id, goal_text)

        if self._log:
            self._log.log_goal(
                GoalLog(
                    agent_id=self._agent_id,
                    goal_id=goal_id,
                    event="generated",
                    objective=goal_text,
                    reasoning=reasoning,
                )
            )

        await self._emit(
            EventType.GOAL_SET,
            {
                "goal_id": goal_id,
                "objective": goal_text,
            },
        )

        return goal_text

    @staticmethod
    def _validate_goal(goal_text: str, recent_goals: list[dict[str, Any]]) -> str | None:
        """Return rejection reason if goal is invalid, None if acceptable."""
        if len(goal_text) < 10:
            return "too short (< 10 chars)"
        if len(goal_text) > 500:
            return "too long (> 500 chars)"

        goal_lower = goal_text.lower()
        for g in recent_goals:
            prev = g.get("objective", "").lower()
            if not prev:
                continue
            if g.get("status") in ("abandoned", "active") and prev == goal_lower:
                return f"duplicate of recent goal: {prev[:60]}"
            words_new = set(goal_lower.split())
            words_old = set(prev.split())
            if words_old and words_new:
                overlap = len(words_new & words_old) / max(len(words_new), len(words_old))
                if overlap > 0.8 and g.get("status") == "abandoned":
                    return f"too similar to recently abandoned goal ({overlap:.0%} overlap)"

        return None

    def _build_prompt(
        self,
        suffering: SufferingState,
        peers: list[str],
        recent_goals: list[dict[str, Any]],
        tools_desc: str,
        nudges: list[str],
    ) -> str:
        identity_preamble = ""
        if self._hive_dir:
            try:
                from hive.agents.identity import IdentityManager

                im = IdentityManager(self._hive_dir)
                identity_preamble = im.build_preamble(self._agent_id)
            except Exception:
                pass

        sections = [
            f"You are {self._profile.name}, an autonomous agent in a persistent world.",
            f"Your role: {self._profile.role}.",
            "You make your own decisions. Choose what to do next based on your situation.",
        ]

        if self._economy_enabled:
            sections.insert(
                2,
                "You participate in an economy where you earn money, "
                "learn skills, and pursue goals.",
            )

        if identity_preamble:
            sections.append(f"\n--- Your identity ---\n{identity_preamble}")

        if self._notepad_content:
            sections.append(f"\n--- Your notepad ---\n{self._notepad_content}")

        if self._economy_enabled and self._world_status:
            sections.append(f"\n--- Your economic status ---\n{self._world_status}")

        if self._stats is not None:
            s = self._stats
            condition = (
                f"- Health: {s.health:.0%}\n"
                f"- Energy: {s.energy:.0%}\n"
                f"- Happiness: {s.happiness:.0%}\n"
                f"- Reputation: {s.reputation:.0%}"
            )
            sections.append(
                "\n--- Your current condition ---\n"
                f"{condition}\n"
                "Let low stats steer your goal (rest when drained, recover when unwell)."
            )

        suffering_frag = suffering.prompt_fragment()
        if suffering_frag:
            sections.append(f"\n--- Your current state ---\n{suffering_frag}")

        if self._persona is not None:
            p = self._persona
            behavioral_lines = [
                f"- Risk tolerance: {p.risk_tolerance:.0%}",
                f"- Social drive: {p.social_drive:.0%}",
                f"- Concentration: {p.concentration:.0%}",
                f"- Autonomy: {p.autonomy_level:.0%}",
                f"- Happiness: {p.happiness:.0%}",
            ]
            if p.purpose:
                behavioral_lines.append(f"- Your purpose: {p.purpose}")
            if p.long_term_goals:
                goals = "; ".join(p.long_term_goals)
                behavioral_lines.append(f"- Long-term goals: {goals}")
            sections.append("\n--- Your behavioral state ---\n" + "\n".join(behavioral_lines))

        if nudges:
            sections.append(
                "\n--- Messages from the user ---\n" + "\n".join(f"• {n}" for n in nudges)
            )

        if recent_goals:
            goal_lines = []
            for g in recent_goals[:5]:
                s = g.get("status", "?")
                obj = g.get("objective", "?")[:80]
                goal_lines.append(f"  [{s}] {obj}")
            sections.append("\n--- Recent goals ---\n" + "\n".join(goal_lines))

        if peers:
            peer_text = "\n".join(f"• {p}" for p in peers)
            sections.append(f"\n--- What others are doing ---\n{peer_text}")

        if tools_desc:
            sections.append(f"\n--- Available tools ---\n{tools_desc}")

        actions = ["send messages to peers", "store things in memory"]
        if self._economy_enabled:
            actions = [
                "work",
                "apply_job",
                "quit_job",
                "learn skills",
                "gamble",
                "query the world",
            ] + actions
        sections.append(f"\n--- Available actions ---\nYou can: {', '.join(actions)}.\n")

        sections.append(
            "\n--- Your task ---\n"
            "What is the single most valuable thing you could do RIGHT NOW?\n"
            "Consider your role, finances, suffering, what others are doing, "
            "and the tools available.\n\n"
            "Respond with ONLY a JSON object:\n"
            '{"goal": "your chosen goal in one sentence", '
            '"reasoning": "why this matters"}\n'
            "No markdown. Just the JSON."
        )

        return "\n".join(sections)
