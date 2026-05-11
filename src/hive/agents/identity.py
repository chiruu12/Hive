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


class AgentIdentity(BaseModel):
    agent_id: str
    display_name: str
    traits: list[str] = []
    domains: list[str] = []
    narrative: str = ""
    worldview: str = ""
    opinions: list[dict[str, Any]] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


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
        identity = AgentIdentity(
            agent_id=agent_id,
            display_name=self._pick_name(),
            traits=profile.personality.traits[:4],
            domains=[profile.role[:50]],
        )
        self.save(identity)
        return identity

    def load(self, agent_id: str) -> AgentIdentity | None:
        path = self._path(agent_id)
        if not path.exists():
            return None
        try:
            return AgentIdentity.model_validate_json(path.read_text())
        except (json.JSONDecodeError, ValueError):
            return None

    def load_or_create(self, agent_id: str, profile: AgentProfile) -> AgentIdentity:
        existing = self.load(agent_id)
        if existing:
            return existing
        return self.create(agent_id, profile)

    def save(self, identity: AgentIdentity) -> None:
        path = self._path(identity.agent_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(identity.model_dump_json(indent=2))
        tmp.rename(path)

    def update_narrative(self, agent_id: str, goal_text: str, outcome: str) -> None:
        identity = self.load(agent_id)
        if not identity:
            return
        entry = f"[{datetime.now(UTC).strftime('%m-%d')}] {goal_text}: {outcome}"
        identity.narrative = (identity.narrative + "\n" + entry).strip()
        if len(identity.narrative) > MAX_NARRATIVE:
            lines = identity.narrative.splitlines()
            while len(identity.narrative) > MAX_NARRATIVE and len(lines) > 1:
                lines.pop(0)
                identity.narrative = "\n".join(lines)
        self.save(identity)

    def add_opinion(self, agent_id: str, domain: str, opinion: str) -> None:
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
        identity = self.load(agent_id)
        if not identity:
            return
        identity.open_questions.append(question)
        if len(identity.open_questions) > MAX_QUESTIONS:
            identity.open_questions = identity.open_questions[-MAX_QUESTIONS:]
        self.save(identity)

    def build_preamble(self, agent_id: str) -> str:
        identity = self.load(agent_id)
        if not identity:
            return ""

        parts = [f"Your name is {identity.display_name}."]

        if identity.traits:
            parts.append(f"Traits: {', '.join(identity.traits)}")

        if identity.domains:
            parts.append(f"Expertise: {', '.join(identity.domains)}")

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
