"""Swarm learning — collective intelligence from agent outcomes."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from hive.agents.specialization import SpecializationTracker
from hive.memory.store import HiveStore


class Recommendation(BaseModel):
    rec_id: str
    category: str
    priority: int = 5
    description: str
    target_agent: str = ""
    cycle_id: int = 0


class LearningReport(BaseModel):
    cycle_id: int
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    swarm_success_rate: float = 0.0
    agent_count: int = 0
    total_goals: int = 0
    total_completed: int = 0
    total_abandoned: int = 0
    pattern_count: int = 0
    specialization_avg: float = 0.0
    recommendations: list[Recommendation] = []
    deltas: dict[str, float] = {}


class SwarmPattern(BaseModel):
    pattern_id: str
    description: str
    pattern_type: str
    agent_count: int = 0
    confidence: float = 0.0


class SwarmLearning:
    """Orchestrates collective learning across all agents."""

    def __init__(
        self,
        store: HiveStore,
        tracker: SpecializationTracker,
    ):
        self._store = store
        self._tracker = tracker
        self._cycle_count = 0
        self._reports: list[LearningReport] = []
        self._patterns: list[SwarmPattern] = []

    async def run_cycle(self, agent_ids: list[str]) -> LearningReport:
        """Run one learning cycle: analyze, find patterns, recommend."""
        self._cycle_count += 1

        total_goals = 0
        total_completed = 0
        total_abandoned = 0
        recs: list[Recommendation] = []

        for aid in agent_ids:
            goals = await self._store.list_agent_goals(aid, limit=50)
            completed = sum(1 for g in goals if g.get("status") == "completed")
            abandoned = sum(1 for g in goals if g.get("status") == "abandoned")
            total_goals += len(goals)
            total_completed += completed
            total_abandoned += abandoned

            if abandoned > completed and len(goals) >= 3:
                recs.append(
                    Recommendation(
                        rec_id=f"rec-{self._cycle_count}-{aid[:8]}",
                        category="routing",
                        priority=8,
                        description=f"Agent {aid[:12]} has more abandoned than completed goals. "
                        "Consider simpler goals or different task routing.",
                        target_agent=aid,
                        cycle_id=self._cycle_count,
                    )
                )

        profiles = self._tracker.get_all_profiles()
        spec_scores = [p.specialization_score for p in profiles.values()]
        spec_avg = sum(spec_scores) / len(spec_scores) if spec_scores else 0.0

        patterns = self._extract_patterns(agent_ids, profiles)
        self._patterns = patterns

        success_rate = total_completed / max(total_goals, 1) if total_goals > 0 else 0.0

        if success_rate < 0.3 and total_goals >= 5:
            recs.append(
                Recommendation(
                    rec_id=f"rec-{self._cycle_count}-swarm",
                    category="knowledge",
                    priority=9,
                    description=f"Swarm success rate is {success_rate:.0%}. "
                    "Agents may need simpler goals or better tool usage.",
                    cycle_id=self._cycle_count,
                )
            )

        for aid in agent_ids:
            profile = profiles.get(aid)
            if profile and profile.weaknesses:
                worst = profile.weaknesses[0]
                if worst.sample_count >= 3 and worst.success_rate < 0.3:
                    recs.append(
                        Recommendation(
                            rec_id=f"rec-{self._cycle_count}-skill-{aid[:8]}",
                            category="specialization",
                            priority=6,
                            description=(
                                f"Agent {aid[:12]} struggles with {worst.task_type} "
                                f"({worst.success_rate:.0%} success). "
                                "Route these tasks elsewhere."
                            ),
                            target_agent=aid,
                            cycle_id=self._cycle_count,
                        )
                    )

        deltas = {}
        if self._reports:
            prev = self._reports[-1]
            deltas["success_rate_delta"] = success_rate - prev.swarm_success_rate
            deltas["goal_delta"] = float(total_goals - prev.total_goals)
            deltas["pattern_delta"] = float(len(patterns) - prev.pattern_count)

        report = LearningReport(
            cycle_id=self._cycle_count,
            swarm_success_rate=success_rate,
            agent_count=len(agent_ids),
            total_goals=total_goals,
            total_completed=total_completed,
            total_abandoned=total_abandoned,
            pattern_count=len(patterns),
            specialization_avg=spec_avg,
            recommendations=recs,
            deltas=deltas,
        )

        self._reports.append(report)
        return report

    def _extract_patterns(
        self,
        agent_ids: list[str],
        profiles: dict[str, Any],
    ) -> list[SwarmPattern]:
        patterns = []

        all_task_types: dict[str, list[str]] = {}
        for aid, profile in profiles.items():
            for s in profile.strengths:
                all_task_types.setdefault(s.task_type, []).append(aid)

        for task_type, agents in all_task_types.items():
            if len(agents) >= 2:
                patterns.append(
                    SwarmPattern(
                        pattern_id=f"shared-{task_type}",
                        description=f"Multiple agents handle {task_type}",
                        pattern_type="shared_capability",
                        agent_count=len(agents),
                        confidence=0.8,
                    )
                )

        specialist_count = sum(1 for p in profiles.values() if p.specialization_score > 0.3)
        if specialist_count > 0:
            patterns.append(
                SwarmPattern(
                    pattern_id="specialization-emerging",
                    description=f"{specialist_count} agents developing specializations",
                    pattern_type="specialization",
                    agent_count=specialist_count,
                    confidence=0.7,
                )
            )

        return patterns

    def get_latest_report(self) -> LearningReport | None:
        return self._reports[-1] if self._reports else None

    def improvement_trend(self) -> float:
        """Linear slope of success rates across cycles. >0 = improving."""
        if len(self._reports) < 2:
            return 0.0
        rates = [r.swarm_success_rate for r in self._reports]
        n = len(rates)
        x_mean = (n - 1) / 2
        y_mean = sum(rates) / n
        num = sum((i - x_mean) * (r - y_mean) for i, r in enumerate(rates))
        den = sum((i - x_mean) ** 2 for i in range(n))
        return num / den if den > 0 else 0.0
