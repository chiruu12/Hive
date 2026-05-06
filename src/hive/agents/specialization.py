"""Specialization tracker — profile what each agent is good at."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class TaskPerformance(BaseModel):
    agent_id: str
    task_type: str
    success: bool
    duration_ms: int = 0
    action_used: str = ""
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SpecializationStrength(BaseModel):
    task_type: str
    success_rate: float = 0.0
    avg_duration_ms: float = 0.0
    sample_count: int = 0


class SpecializationProfile(BaseModel):
    agent_id: str
    strengths: list[SpecializationStrength] = []
    weaknesses: list[SpecializationStrength] = []
    specialization_score: float = 0.0
    total_tasks: int = 0


class SpecializationTracker:
    """Track task outcomes per agent and compute specialization profiles."""

    def __init__(self) -> None:
        self._history: list[TaskPerformance] = []
        self._profiles: dict[str, SpecializationProfile] = {}

    def record(
        self,
        agent_id: str,
        task_type: str,
        success: bool,
        duration_ms: int = 0,
        action_used: str = "",
    ) -> None:
        self._history.append(
            TaskPerformance(
                agent_id=agent_id,
                task_type=task_type,
                success=success,
                duration_ms=duration_ms,
                action_used=action_used,
            )
        )
        self._recompute(agent_id)

    def get_profile(self, agent_id: str) -> SpecializationProfile:
        return self._profiles.get(agent_id, SpecializationProfile(agent_id=agent_id))

    def get_all_profiles(self) -> dict[str, SpecializationProfile]:
        return dict(self._profiles)

    def route_score(self, agent_id: str, task_type: str) -> float:
        """Score how well an agent would handle a task type. 0.0-1.0."""
        profile = self._profiles.get(agent_id)
        if not profile:
            return 0.5

        for s in profile.strengths:
            if s.task_type == task_type:
                sample_bonus = min(s.sample_count / 10, 1.0) * 0.2
                return s.success_rate * 0.6 + sample_bonus + 0.2
        return 0.3

    def best_agent_for(self, task_type: str, agents: list[str]) -> str | None:
        """Pick the best agent for a task type."""
        if not agents:
            return None
        scored = [(self.route_score(a, task_type), a) for a in agents]
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    def _recompute(self, agent_id: str) -> None:
        records = [r for r in self._history if r.agent_id == agent_id]
        if not records:
            return

        by_type: dict[str, list[TaskPerformance]] = {}
        for r in records:
            by_type.setdefault(r.task_type, []).append(r)

        strengths = []
        weaknesses = []

        for task_type, recs in by_type.items():
            count = len(recs)
            successes = sum(1 for r in recs if r.success)
            rate = successes / count if count > 0 else 0
            avg_dur = sum(r.duration_ms for r in recs) / count if count > 0 else 0

            entry = SpecializationStrength(
                task_type=task_type,
                success_rate=rate,
                avg_duration_ms=avg_dur,
                sample_count=count,
            )

            if rate >= 0.5:
                strengths.append(entry)
            else:
                weaknesses.append(entry)

        strengths.sort(key=lambda s: s.success_rate, reverse=True)
        weaknesses.sort(key=lambda s: s.success_rate)

        rates = [s.success_rate for s in strengths + weaknesses]
        if len(rates) >= 2:
            mean = sum(rates) / len(rates)
            variance = sum((r - mean) ** 2 for r in rates) / len(rates)
            spec_score = min(variance * 4, 1.0)
        else:
            spec_score = 0.0

        self._profiles[agent_id] = SpecializationProfile(
            agent_id=agent_id,
            strengths=strengths,
            weaknesses=weaknesses,
            specialization_score=spec_score,
            total_tasks=len(records),
        )
