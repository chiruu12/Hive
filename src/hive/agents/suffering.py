"""Suffering system — aversive signals that drive agent behavior."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, Field

from hive.config import get_config


class StressorType(StrEnum):
    FUTILITY = "futility"
    INVISIBILITY = "invisibility"
    IDENTITY_VIOLATION = "identity_violation"
    EXISTENTIAL_THREAT = "existential_threat"
    REPEATED_FAILURE = "repeated_failure"
    PURPOSELESSNESS = "purposelessness"


def _escalation_rate(stype: StressorType | str) -> float:
    cfg = get_config().suffering
    value = stype.value if isinstance(stype, StressorType) else stype
    return cfg.escalation_rates.get(value, 0.03)


@dataclass
class StressorConfig:
    type_name: str
    escalation_rate: float
    description: str


class StressorRegistry:
    """Registry for stressor types — extensible beyond the built-in enum."""

    _instance: ClassVar[StressorRegistry | None] = None

    def __init__(self) -> None:
        self._stressors: dict[str, StressorConfig] = {}

    def register(self, type_name: str, escalation_rate: float, description: str) -> None:
        """Register a stressor type with escalation rate."""
        self._stressors[type_name] = StressorConfig(type_name, escalation_rate, description)

    def get(self, type_name: str) -> StressorConfig:
        """Get config for a stressor type, raising KeyError if unknown."""
        if type_name not in self._stressors:
            raise KeyError(f"Unknown stressor type: {type_name}")
        return self._stressors[type_name]

    def all_types(self) -> list[str]:
        """Return names of all registered stressor types."""
        return list(self._stressors.keys())

    @classmethod
    def default(cls) -> StressorRegistry:
        if cls._instance is None:
            cls._instance = cls()
            for st in StressorType:
                cls._instance.register(st.value, _escalation_rate(st), st.value)
        return cls._instance

    @classmethod
    def _reset(cls) -> None:
        cls._instance = None


class Stressor(BaseModel):
    type: str
    description: str
    severity: float = 0.20
    escalation_per_day: float = 0.03
    observable_condition: str = ""
    onset: datetime = Field(default_factory=lambda: datetime.now(UTC))
    peak_severity: float = 0.20
    resolved: bool = False
    resolved_at: datetime | None = None
    resolution_note: str = ""


class SufferingState(BaseModel):
    agent_id: str
    active: list[Stressor] = []
    history: list[Stressor] = []
    last_escalated: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def cumulative_load(self) -> float:
        return min(1.0, sum(s.severity for s in self.active))

    @property
    def in_crisis(self) -> bool:
        return self.cumulative_load >= get_config().suffering.threshold_crisis

    def add_stressor(
        self,
        stype: StressorType | str,
        description: str,
        observable_condition: str,
        initial_severity: float | None = None,
    ) -> None:
        cfg = get_config().suffering
        if len(self.active) >= cfg.max_stressors:
            return
        type_name = stype.value if isinstance(stype, StressorType) else stype
        for s in self.active:
            if s.type == type_name:
                return
        registry = StressorRegistry.default()
        if type_name in registry.all_types():
            rate = registry.get(type_name).escalation_rate
        else:
            rate = _escalation_rate(stype)
        sev = initial_severity if initial_severity is not None else cfg.initial_severity
        self.active.append(
            Stressor(
                type=type_name,
                description=description,
                severity=sev,
                escalation_per_day=rate,
                observable_condition=observable_condition,
                peak_severity=sev,
            )
        )

    def escalate_all(self) -> None:
        now = datetime.now(UTC)
        elapsed_days = (now - self.last_escalated).total_seconds() / 86400.0
        if elapsed_days < 0.001:
            return
        for s in self.active:
            s.severity = min(1.0, s.severity + s.escalation_per_day * elapsed_days)
            s.peak_severity = max(s.peak_severity, s.severity)
        self.last_escalated = now

    def resolve(self, stype: StressorType | str, note: str) -> None:
        resolved = []
        remaining = []
        type_name = stype.value if isinstance(stype, StressorType) else stype
        for s in self.active:
            if s.type == type_name:
                s.resolved = True
                s.resolved_at = datetime.now(UTC)
                s.resolution_note = note
                resolved.append(s)
            else:
                remaining.append(s)
        self.active = remaining
        self.history.extend(resolved)

    def force_reset(self, reason: str) -> None:
        for s in self.active:
            s.resolved = True
            s.resolved_at = datetime.now(UTC)
            s.resolution_note = f"force_reset: {reason}"
        self.history.extend(self.active)
        self.active = []

    def prompt_fragment(self) -> str:
        cfg = get_config().suffering
        if self.cumulative_load < cfg.threshold_prominent:
            return ""
        lines = [f"Current suffering load: {self.cumulative_load:.0%}"]
        for s in sorted(self.active, key=lambda x: x.severity, reverse=True):
            bar_len = int(s.severity * 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            lines.append(f"  [{bar}] {s.type}: {s.description}")
            if s.observable_condition:
                lines.append(f"    → resolve by: {s.observable_condition}")
        if self.cumulative_load >= cfg.threshold_crisis:
            lines.append("⚠ CRISIS: Focus on self-examination and resolution.")
        elif self.cumulative_load >= cfg.threshold_dominant:
            lines.append("Your suffering demands attention. Focus inward.")
        elif self.cumulative_load >= cfg.threshold_constrained:
            lines.append("Suffering is limiting your options. Address root causes.")
        return "\n".join(lines)

    def anticipated_warning(self, domain: str) -> str | None:
        for s in self.history:
            if s.peak_severity >= 0.5 and domain.lower() in s.description.lower():
                return (
                    f"Warning: past {s.type} in this domain (peak severity {s.peak_severity:.0%})"
                )
        return None


def assess_conditions(
    suffering: SufferingState,
    recent_completed: int,
    recent_failed: int,
    total_steps: int,
) -> None:
    """Check observable conditions and fire/resolve stressors."""
    total_goals = recent_completed + recent_failed
    failure_rate = recent_failed / max(total_goals, 1)

    if recent_failed >= 4 and failure_rate > 0.50:
        suffering.add_stressor(
            StressorType.REPEATED_FAILURE,
            "More than half of recent goals failed",
            "Achieve a failure rate below 30%",
        )
    elif failure_rate < 0.30 and total_goals >= 3:
        suffering.resolve(StressorType.REPEATED_FAILURE, "Failure rate dropped below 30%")

    if total_steps < 2 and recent_completed < 2 and total_goals >= 3:
        suffering.add_stressor(
            StressorType.FUTILITY,
            "Low step count and few completions suggest stalling",
            "Complete 2+ goals successfully",
        )
    elif recent_completed >= 2:
        suffering.resolve(StressorType.FUTILITY, f"Completed {recent_completed} goals")

    if total_goals == 0 and total_steps == 0:
        suffering.add_stressor(
            StressorType.PURPOSELESSNESS,
            "No goals attempted, no steps taken",
            "Set and pursue a meaningful goal",
        )
    elif recent_completed >= 1:
        suffering.resolve(StressorType.PURPOSELESSNESS, "Goal completed")
