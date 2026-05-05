"""Suffering system — aversive signals that drive agent behavior."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

THRESHOLD_PROMINENT = 0.35
THRESHOLD_CONSTRAINED = 0.55
THRESHOLD_DOMINANT = 0.75
THRESHOLD_CRISIS = 0.90
MAX_STRESSORS = 5


class StressorType(StrEnum):
    FUTILITY = "futility"
    INVISIBILITY = "invisibility"
    IDENTITY_VIOLATION = "identity_violation"
    EXISTENTIAL_THREAT = "existential_threat"
    REPEATED_FAILURE = "repeated_failure"
    PURPOSELESSNESS = "purposelessness"


ESCALATION_RATES: dict[StressorType, float] = {
    StressorType.FUTILITY: 0.025,
    StressorType.INVISIBILITY: 0.030,
    StressorType.REPEATED_FAILURE: 0.040,
    StressorType.PURPOSELESSNESS: 0.035,
    StressorType.IDENTITY_VIOLATION: 0.060,
    StressorType.EXISTENTIAL_THREAT: 0.070,
}


class Stressor(BaseModel):
    type: StressorType
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
        return self.cumulative_load >= THRESHOLD_CRISIS

    def add_stressor(
        self,
        stype: StressorType,
        description: str,
        observable_condition: str,
        initial_severity: float = 0.20,
    ) -> None:
        if len(self.active) >= MAX_STRESSORS:
            return
        for s in self.active:
            if s.type == stype:
                return
        rate = ESCALATION_RATES.get(stype, 0.03)
        self.active.append(
            Stressor(
                type=stype,
                description=description,
                severity=initial_severity,
                escalation_per_day=rate,
                observable_condition=observable_condition,
                peak_severity=initial_severity,
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

    def resolve(self, stype: StressorType, note: str) -> None:
        resolved = []
        remaining = []
        for s in self.active:
            if s.type == stype:
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
        if self.cumulative_load < THRESHOLD_PROMINENT:
            return ""
        lines = [f"Current suffering load: {self.cumulative_load:.0%}"]
        for s in sorted(self.active, key=lambda x: x.severity, reverse=True):
            bar_len = int(s.severity * 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            lines.append(f"  [{bar}] {s.type.value}: {s.description}")
            if s.observable_condition:
                lines.append(f"    → resolve by: {s.observable_condition}")
        if self.cumulative_load >= THRESHOLD_CRISIS:
            lines.append("⚠ CRISIS: Focus on self-examination and resolution.")
        elif self.cumulative_load >= THRESHOLD_DOMINANT:
            lines.append("Your suffering demands attention. Focus inward.")
        elif self.cumulative_load >= THRESHOLD_CONSTRAINED:
            lines.append("Suffering is limiting your options. Address root causes.")
        return "\n".join(lines)

    def anticipated_warning(self, domain: str) -> str | None:
        for s in self.history:
            if s.peak_severity >= 0.5 and domain.lower() in s.description.lower():
                return (
                    f"Warning: past {s.type.value} in this domain "
                    f"(peak severity {s.peak_severity:.0%})"
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
