"""Existence loop — autonomous goal generation when agent is idle."""

import logging
from uuid import uuid4

from hive.agents.base import AgentLoopBase
from hive.agents.profile import AgentProfile
from hive.agents.suffering import SufferingState
from hive.execution.context import ExecutionContext
from hive.logging.models import DecisionLog, GoalLog
from hive.logging.writer import LogWriter
from hive.memory.events import EventLog, EventType
from hive.memory.store import HiveStore
from hive.models.claude import ClaudeCLIProvider

logger = logging.getLogger(__name__)


class ExistenceLoop(AgentLoopBase):
    """Generates autonomous goals from agent context when idle."""

    def __init__(
        self,
        agent_id: str,
        profile: AgentProfile,
        provider: ClaudeCLIProvider,
        ctx: ExecutionContext,
        store: HiveStore,
        event_log: EventLog,
        log_writer: LogWriter | None = None,
        session_id: str = "",
    ):
        super().__init__(agent_id, profile, provider, ctx, store, event_log, log_writer, session_id)

    async def generate_goal(
        self,
        suffering: SufferingState,
        peer_summaries: list[str],
        nudges: list[str],
    ) -> str | None:
        """Build context and ask Claude what the agent should do next."""
        recent_goals = await self._store.list_agent_goals(self._agent_id, limit=5)

        tool_schemas = ""
        try:
            from hive.execution.registry import get_registry

            tool_schemas = get_registry().get_tool_schemas()
        except RuntimeError:
            pass

        prompt = self._build_prompt(suffering, peer_summaries, recent_goals, tool_schemas, nudges)

        response = await self._provider.complete(
            messages=[{"role": "user", "content": prompt}],
            system=self._profile.build_system_prompt(),
        )

        parsed = self._parse_json(response.content)
        goal_text = parsed.get("goal") if parsed else None
        reasoning = parsed.get("reasoning") if parsed else None

        if self._log:
            self._log.log_decision(
                DecisionLog(
                    agent_id=self._agent_id,
                    decision_type="existence",
                    model=response.model,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    cost_usd=response.cost_usd,
                    duration_ms=response.duration_ms,
                    response_raw=response.content,
                    response_parsed=parsed,
                    success=goal_text is not None,
                )
            )

        if not goal_text:
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

    def _build_prompt(
        self,
        suffering: SufferingState,
        peers: list[str],
        recent_goals: list[dict],
        tools_desc: str,
        nudges: list[str],
    ) -> str:
        identity_preamble = ""
        try:
            from hive.agents.identity import IdentityManager

            im = IdentityManager(self._ctx.comms_dir.parent)
            identity_preamble = im.build_preamble(self._agent_id)
        except Exception:
            pass

        sections = [
            f"You are {self._profile.name}, an autonomous agent in a persistent world.",
            f"Your role: {self._profile.role}.",
            "You exist in an economy where you earn money, learn skills, and pursue goals.",
            "You make your own decisions. Choose what to do next based on your situation.",
        ]

        if identity_preamble:
            sections.append(f"\n--- Your identity ---\n{identity_preamble}")

        status = self._ctx.world.get_status(self._agent_id)
        sections.append(f"\n--- Your economic status ---\n{status}")

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
                s = g.get("status", "?")
                obj = g.get("objective", "?")[:80]
                goal_lines.append(f"  [{s}] {obj}")
            sections.append("\n--- Recent goals ---\n" + "\n".join(goal_lines))

        if peers:
            peer_text = "\n".join(f"• {p}" for p in peers)
            sections.append(f"\n--- What others are doing ---\n{peer_text}")

        if tools_desc:
            sections.append(f"\n--- Available tools ---\n{tools_desc}")

        sections.append(
            "\n--- Available actions ---\n"
            "You can: work, apply_job, quit_job, learn skills, gamble,\n"
            "send messages to peers, store things in memory, query the world.\n"
        )

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
