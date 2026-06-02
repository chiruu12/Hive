"""Agent identity — persistent self with name, narrative, opinions."""

import json
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from hive.agents.profile import AgentProfile

_NAME_POOL = [
    "Atlas",
    "Beacon",
    "Cipher",
    "Drift",
    "Echo",
    "Flux",
    "Glyph",
    "Helix",
    "Iris",
    "Jolt",
    "Kite",
    "Loom",
    "Muse",
    "Nexus",
    "Onyx",
    "Pulse",
    "Quill",
    "Rune",
    "Spark",
    "Tide",
    "Unity",
    "Vex",
    "Wren",
    "Apex",
    "Blaze",
    "Coral",
    "Dusk",
    "Ember",
    "Forge",
    "Ghost",
    "Haze",
    "Ivory",
    "Jade",
    "Knox",
    "Lyric",
    "Maze",
    "Nova",
    "Orbit",
    "Pike",
    "Quest",
    "Ridge",
    "Sable",
    "Thorn",
    "Vale",
    "Wisp",
    "Zenith",
    "Aura",
    "Brio",
]

MAX_NARRATIVE = 800
MAX_OPINIONS = 20
MAX_QUESTIONS = 12
MAX_CHAPTERS = 20


def _entry_date(line: str) -> str:
    """Extract the bracketed date prefix from a ``[date] ...`` narrative line."""
    if line.startswith("[") and "]" in line:
        return line[1 : line.index("]")]
    return ""


def _entry_goal(line: str) -> str:
    """Extract the goal text from a ``[date] goal: outcome`` narrative line."""
    body = line.split("] ", 1)[-1]
    return body.rsplit(": ", 1)[0].strip()[:48]


class Chapter(BaseModel):
    """A sealed span of an agent's narrative.

    When the open narrative grows past ``MAX_NARRATIVE`` it is sealed into a
    Chapter (a compact summary) rather than FIFO-dropping its oldest lines, so
    long-run history is preserved as a story arc instead of being lost.
    """

    index: int
    summary: str
    entry_count: int
    started: str = ""
    ended: str = ""


class AgentIdentity(BaseModel):
    agent_id: str
    display_name: str
    traits: list[str] = []
    domains: list[str] = []
    narrative: str = ""
    chapters: list[Chapter] = Field(default_factory=list)
    worldview: str = ""
    opinions: list[dict[str, Any]] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def full_narrative(self) -> str:
        """The whole story: sealed chapter summaries + the current open narrative.

        ``narrative`` alone holds only the current (unsealed) chapter, so callers
        that want the agent's complete history (e.g. life summaries) must use this.
        """
        parts: list[str] = []
        if self.chapters:
            parts.append("\n".join(f"- {c.summary}" for c in self.chapters))
        if self.narrative:
            parts.append(self.narrative)
        return "\n\n".join(parts)


class IdentityManager:
    """Creates, loads, saves, and builds LLM preambles from agent identities."""

    def __init__(self, hive_dir: Path):
        self._dir = hive_dir / "identity"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._claimed: set[str] = set()
        self._load_claimed()

    def _load_claimed(self) -> None:
        for f in self._dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                self._claimed.add(data.get("display_name", ""))
            except (json.JSONDecodeError, OSError):
                pass

    def _pick_name(self) -> str:
        available = [n for n in _NAME_POOL if n not in self._claimed]
        if not available:
            return f"Agent-{random.randint(1000, 9999)}"
        name = random.choice(available)
        self._claimed.add(name)
        return name

    def _path(self, agent_id: str) -> Path:
        return self._dir / f"{agent_id}.json"

    def create(self, agent_id: str, profile: AgentProfile) -> AgentIdentity:
        """Create a new identity for an agent."""
        identity = AgentIdentity(
            agent_id=agent_id,
            display_name=self._pick_name(),
            traits=profile.personality.traits[:4],
            domains=[profile.role[:50]],
        )
        self.save(identity)
        return identity

    def load(self, agent_id: str) -> AgentIdentity | None:
        """Load identity from disk, or None if not found."""
        path = self._path(agent_id)
        if not path.exists():
            return None
        try:
            return AgentIdentity.model_validate_json(path.read_text())
        except (json.JSONDecodeError, ValueError):
            return None

    def load_or_create(self, agent_id: str, profile: AgentProfile) -> AgentIdentity:
        """Load existing identity or create a new one."""
        existing = self.load(agent_id)
        if existing:
            return existing
        return self.create(agent_id, profile)

    def save(self, identity: AgentIdentity) -> None:
        """Persist identity to disk atomically."""
        path = self._path(identity.agent_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(identity.model_dump_json(indent=2))
        tmp.rename(path)

    def update_narrative(self, agent_id: str, goal_text: str, outcome: str) -> None:
        """Append a goal outcome to the agent's narrative.

        When the open narrative would overflow ``MAX_NARRATIVE``, it is sealed
        into a Chapter first (preserving the history as a summary) and the new
        entry starts a fresh chapter -- rather than FIFO-dropping old lines.
        """
        identity = self.load(agent_id)
        if not identity:
            return
        # Normalize newlines: a multi-line goal/outcome (e.g. LLM text) would
        # otherwise split one entry across lines and break chapter sealing
        # (entry_count / date / goal extraction all operate per-line).
        goal_text = goal_text.replace("\n", " ").replace("\r", " ")
        outcome = outcome.replace("\n", " ").replace("\r", " ")
        # Full date (%Y-%m-%d) so chapter spans are unambiguous across year boundaries.
        entry = f"[{datetime.now(UTC).strftime('%Y-%m-%d')}] {goal_text}: {outcome}"
        # Cap a single pathological entry so the open narrative can never exceed
        # MAX_NARRATIVE (a lone over-long entry would otherwise bypass sealing).
        if len(entry) > MAX_NARRATIVE:
            entry = entry[: MAX_NARRATIVE - 1] + "…"
        if identity.narrative and len(identity.narrative) + len(entry) + 1 > MAX_NARRATIVE:
            self._seal_chapter(identity)
        identity.narrative = (identity.narrative + "\n" + entry).strip()
        self.save(identity)

    @staticmethod
    def _seal_chapter(identity: AgentIdentity) -> None:
        """Roll the open narrative into a sealed Chapter and clear it."""
        lines = [ln for ln in identity.narrative.splitlines() if ln.strip()]
        if not lines:
            identity.narrative = ""  # defensive: clear a whitespace-only narrative
            return
        started = _entry_date(lines[0])
        ended = _entry_date(lines[-1])
        index = identity.chapters[-1].index + 1 if identity.chapters else 1
        if started and ended and started != ended:
            span = f" ({started}–{ended})"
        elif started:
            span = f" ({started})"
        else:
            span = ""
        # Carry goal text so the summary is semantically useful, not just a count:
        # the first goal (theme) and, if different, the last (arc).
        first_goal = _entry_goal(lines[0])
        last_goal = _entry_goal(lines[-1])
        theme = first_goal if first_goal == last_goal else f"{first_goal} → {last_goal}"
        suffix = f" — {theme}" if theme else ""
        identity.chapters.append(
            Chapter(
                index=index,
                summary=f"Ch{index}{span}: {len(lines)} entries{suffix}",
                entry_count=len(lines),
                started=started,
                ended=ended,
            )
        )
        if len(identity.chapters) > MAX_CHAPTERS:
            identity.chapters = identity.chapters[-MAX_CHAPTERS:]
        identity.narrative = ""

    def add_opinion(self, agent_id: str, domain: str, opinion: str) -> None:
        """Record an opinion the agent has formed."""
        identity = self.load(agent_id)
        if not identity:
            return
        identity.opinions.append(
            {
                "domain": domain,
                "opinion": opinion,
                "formed_at": datetime.now(UTC).isoformat(),
            }
        )
        if len(identity.opinions) > MAX_OPINIONS:
            identity.opinions = identity.opinions[-MAX_OPINIONS:]
        self.save(identity)

    def add_question(self, agent_id: str, question: str) -> None:
        """Add an open question the agent is pondering."""
        identity = self.load(agent_id)
        if not identity:
            return
        identity.open_questions.append(question)
        if len(identity.open_questions) > MAX_QUESTIONS:
            identity.open_questions = identity.open_questions[-MAX_QUESTIONS:]
        self.save(identity)

    def build_preamble(self, agent_id: str) -> str:
        """Build identity context string for LLM prompts (loads from disk)."""
        identity = self.load(agent_id)
        if not identity:
            return ""
        return self.render_preamble(identity)

    @staticmethod
    def render_preamble(identity: AgentIdentity) -> str:
        """Render an identity context string from an already-loaded identity.

        Used both for goal generation and (via the daemon) for goal pursuit, so a
        caller that already holds the identity can avoid a redundant disk read.
        """
        parts = [f"Your name is {identity.display_name}."]

        if identity.traits:
            parts.append(f"Traits: {', '.join(identity.traits)}")

        if identity.domains:
            parts.append(f"Expertise: {', '.join(identity.domains)}")

        if identity.chapters:
            recent_chapters = identity.chapters[-5:]
            chapter_lines = "\n".join(f"  - {c.summary}" for c in recent_chapters)
            parts.append(f"\nStory so far:\n{chapter_lines}")

        if identity.narrative:
            recent = identity.narrative[-400:]
            parts.append(f"\nRecent history:\n{recent}")

        if identity.worldview:
            parts.append(f"\nYour worldview: {identity.worldview}")

        if identity.opinions:
            ops = identity.opinions[-5:]
            op_lines = [f"  - {o['domain']}: {o['opinion']}" for o in ops]
            parts.append("\nYour opinions:\n" + "\n".join(op_lines))

        if identity.open_questions:
            qs = identity.open_questions[-3:]
            parts.append("\nOpen questions: " + "; ".join(qs))

        return "\n".join(parts)
