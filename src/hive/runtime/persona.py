"""Persona — agent identity that evolves at runtime via suffering."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from hive.agents.suffering import StressorType, SufferingState
from hive.runtime.instructions import Instructions

if TYPE_CHECKING:
    from hive.agents.profile import AgentProfile


def _describe_level(value: float, low: str, mid: str, high: str) -> str:
    if value >= 0.7:
        return f"HIGH — {high}"
    if value >= 0.4:
        return f"MODERATE — {mid}"
    return f"LOW — {low}"


class Persona(Instructions):
    """Agent identity that evolves at runtime. Character sheet becomes living entity.

    Static fields (set at init, read during prompt building):
        name, personality, values, fears, purpose, long_term_goals, behavior_style

    Dynamic fields (modified by suffering at runtime):
        risk_tolerance, social_drive, concentration, autonomy_level, happiness

    Usage:
        persona = Persona(
            name="Coder",
            persona="Senior Python developer",
            personality=["methodical", "perfectionist"],
            values=["clean code", "reliability"],
            fears=["shipping bugs"],
            purpose="Build software that works",
            risk_tolerance=0.3,
        )

        agent = Agent(name="coder", model=provider, persona=persona)
    """

    def __init__(
        self,
        persona: str = "",
        instructions: str | list[str] | None = None,
        context: str = "",
        name: str = "",
        personality: list[str] | None = None,
        values: list[str] | None = None,
        fears: list[str] | None = None,
        purpose: str = "",
        long_term_goals: list[str] | None = None,
        behavior_style: str = "",
        risk_tolerance: float = 0.3,
        social_drive: float = 0.5,
        concentration: float = 1.0,
        autonomy_level: float = 0.5,
        happiness: float = 0.7,
        suffering: SufferingState | None = None,
    ):
        super().__init__(persona=persona, instructions=instructions, context=context)
        self.name = name
        self.personality = personality or []
        self.values = values or []
        self.fears = fears or []
        self.purpose = purpose
        self.long_term_goals = long_term_goals or []
        self.behavior_style = behavior_style

        self.risk_tolerance = risk_tolerance
        self.social_drive = social_drive
        self.concentration = concentration
        self.autonomy_level = autonomy_level
        self.happiness = happiness
        self.suffering = suffering

        self._base_risk_tolerance = risk_tolerance
        self._base_social_drive = social_drive
        self._base_concentration = concentration
        self._base_autonomy_level = autonomy_level
        self._base_happiness = happiness

    def build_system_prompt(
        self,
        toolkit_instructions: list[str] | None = None,
        response_model: type[Any] | None = None,
    ) -> str:
        """Assemble system prompt with personality, values, fears, and behavioral state."""
        parts: list[str] = []

        if self.name:
            parts.append(f"You are {self.name}.")
        elif self.persona:
            parts.append(f"You are {self.persona}.")

        if self.personality:
            parts.append(f"Personality: {', '.join(self.personality)}.")

        if self.values:
            parts.append(f"Values: {', '.join(self.values)}.")

        if self.fears:
            parts.append(f"Fears: {', '.join(self.fears)}.")

        if self.purpose:
            parts.append(f"Purpose: {self.purpose}")

        if self.long_term_goals:
            goals_text = "; ".join(self.long_term_goals)
            parts.append(f"Long-term goals: {goals_text}")

        if self._instructions:
            lines = "\n".join(f"- {i}" for i in self._instructions)
            parts.append(f"Instructions:\n{lines}")

        if self.context:
            parts.append(f"Context: {self.context}")

        if self.behavior_style:
            parts.append(f"Behavior style: {self.behavior_style}")

        risk_desc = _describe_level(
            self.risk_tolerance,
            "play it safe",
            "weigh risks carefully",
            "willing to take bigger swings",
        )
        conc_desc = _describe_level(
            self.concentration,
            "scattered, consider simpler goals",
            "focused but distractible",
            "fully focused",
        )
        social_desc = _describe_level(
            self.social_drive,
            "prefer working alone",
            "open to collaboration",
            "crave interaction with peers",
        )
        auto_desc = _describe_level(
            self.autonomy_level,
            "follow instructions closely",
            "balance guidance with initiative",
            "make your own decisions",
        )
        state_lines = [
            "Current behavioral state:",
            f"- Risk tolerance: {risk_desc}",
            f"- Concentration: {conc_desc}",
            f"- Social drive: {social_desc}",
            f"- Autonomy: {auto_desc}",
            f"- Happiness: {self.happiness:.0%}",
        ]
        parts.append("\n".join(state_lines))

        if toolkit_instructions:
            for ti in toolkit_instructions:
                if ti.strip():
                    parts.append(ti)

        block = self._response_schema_block(response_model)
        if block:
            parts.append(block)

        return "\n\n".join(parts)

    def apply_suffering_effects(self) -> None:
        """Read suffering state and modify runtime behavioral params."""
        self.risk_tolerance = self._base_risk_tolerance
        self.social_drive = self._base_social_drive
        self.concentration = self._base_concentration
        self.autonomy_level = self._base_autonomy_level
        self.happiness = self._base_happiness

        if self.suffering is None:
            return

        for stressor in self.suffering.active:
            if stressor.severity <= 0.5:
                continue
            if stressor.type == StressorType.FUTILITY:
                self.risk_tolerance += 0.1
            elif stressor.type == StressorType.INVISIBILITY:
                self.social_drive += 0.15
            elif stressor.type == StressorType.PURPOSELESSNESS:
                self.autonomy_level += 0.2

        for stressor in self.suffering.active:
            if stressor.severity > 0.7:
                self.concentration -= 0.2

        if self.suffering.in_crisis:
            self.risk_tolerance = 0.9
            self.concentration = 0.3

        self._clamp_values()

    def update_from_event(self, event_type: str, outcome: str) -> None:
        """Adjust behavioral params based on life events."""
        if event_type == "goal_completed":
            self._base_happiness = min(1.0, self._base_happiness + 0.05)
            self._base_risk_tolerance = max(0.0, self._base_risk_tolerance - 0.05)
            self.happiness = self._base_happiness
            self.risk_tolerance = self._base_risk_tolerance
        elif event_type in ("goal_failed", "goal_abandoned"):
            self._base_happiness = max(0.0, self._base_happiness - 0.1)
            self.happiness = self._base_happiness

    def snapshot(self) -> dict[str, Any]:
        """Return all fields for checkpointing."""
        return {
            "name": self.name,
            "personality": self.personality,
            "values": self.values,
            "fears": self.fears,
            "purpose": self.purpose,
            "long_term_goals": self.long_term_goals,
            "behavior_style": self.behavior_style,
            "risk_tolerance": self.risk_tolerance,
            "social_drive": self.social_drive,
            "concentration": self.concentration,
            "autonomy_level": self.autonomy_level,
            "happiness": self.happiness,
        }

    def restore_dynamic(self, snap: dict[str, Any]) -> None:
        """Restore dynamic fields from a checkpoint snapshot."""
        self.risk_tolerance = snap.get("risk_tolerance", 0.3)
        self.social_drive = snap.get("social_drive", 0.5)
        self.concentration = snap.get("concentration", 1.0)
        self.autonomy_level = snap.get("autonomy_level", 0.5)
        self.happiness = snap.get("happiness", 0.7)
        self._base_risk_tolerance = self.risk_tolerance
        self._base_social_drive = self.social_drive
        self._base_concentration = self.concentration
        self._base_autonomy_level = self.autonomy_level
        self._base_happiness = self.happiness

    @classmethod
    def from_profile(cls, profile: AgentProfile) -> Persona:
        """Create a Persona from an AgentProfile."""
        pc = getattr(profile, "persona_config", None)
        return cls(
            persona=profile.role,
            name=profile.name,
            personality=profile.personality.traits,
            behavior_style=profile.personality.style,
            context=profile.system_prompt,
            values=pc.values if pc else [],
            fears=pc.fears if pc else [],
            purpose=pc.purpose if pc else "",
            long_term_goals=pc.long_term_goals if pc else [],
            risk_tolerance=pc.risk_tolerance if pc else 0.3,
            social_drive=pc.social_drive if pc else 0.5,
            concentration=pc.concentration if pc else 1.0,
            autonomy_level=pc.autonomy_level if pc else 0.5,
            happiness=pc.happiness if pc else 0.7,
        )

    @classmethod
    def from_yaml(cls, path: Path) -> Persona:
        """Load a Persona directly from a YAML file."""
        import yaml

        with open(path) as f:
            data = yaml.safe_load(f)

        persona_data = data.get("persona", {})
        personality_data = data.get("personality", {})

        return cls(
            persona=data.get("role", ""),
            name=data.get("name", ""),
            personality=personality_data.get("traits", []),
            behavior_style=personality_data.get("style", ""),
            context=data.get("system_prompt", ""),
            values=persona_data.get("values", []),
            fears=persona_data.get("fears", []),
            purpose=persona_data.get("purpose", ""),
            long_term_goals=persona_data.get("long_term_goals", []),
            risk_tolerance=persona_data.get("risk_tolerance", 0.3),
            social_drive=persona_data.get("social_drive", 0.5),
            concentration=persona_data.get("concentration", 1.0),
            autonomy_level=persona_data.get("autonomy_level", 0.5),
            happiness=persona_data.get("happiness", 0.7),
        )

    def _clamp_values(self) -> None:
        self.risk_tolerance = max(0.0, min(1.0, self.risk_tolerance))
        self.social_drive = max(0.0, min(1.0, self.social_drive))
        self.concentration = max(0.2, min(1.0, self.concentration))
        self.autonomy_level = max(0.0, min(1.0, self.autonomy_level))
        self.happiness = max(0.0, min(1.0, self.happiness))

    def __repr__(self) -> str:
        fields = []
        if self.name:
            fields.append(f"name={self.name!r}")
        if self.persona:
            fields.append(f"persona={self.persona!r}")
        if self.personality:
            fields.append(f"personality={self.personality!r}")
        fields.append(f"risk_tolerance={self.risk_tolerance:.2f}")
        fields.append(f"happiness={self.happiness:.2f}")
        return f"Persona({', '.join(fields)})"
