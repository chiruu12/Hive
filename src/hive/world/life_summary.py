"""Life summary — biographical record of an agent's journey."""

from pathlib import Path

from pydantic import BaseModel

from hive.agents.identity import IdentityManager
from hive.memory.store import HiveStore
from hive.world.event_engine import EventEngine
from hive.world.state import WorldState
from hive.world.stats import StatsManager


class LifeMilestone(BaseModel):
    cycle: int
    description: str
    category: str = ""
    stat_snapshot: dict[str, float] = {}


class CareerEntry(BaseModel):
    job_title: str
    started_cycle: int
    ended_cycle: int | None = None
    salary: float = 0.0


class LifeSummary(BaseModel):
    agent_id: str
    display_name: str = ""
    role: str = ""
    traits: list[str] = []
    cycles_lived: int = 0
    real_time: str = ""
    final_stats: dict[str, float] = {}
    final_money: float = 0.0
    career_path: list[CareerEntry] = []
    milestones: list[LifeMilestone] = []
    skills_learned: list[str] = []
    goals_completed: int = 0
    goals_abandoned: int = 0
    times_gambled: int = 0
    gambling_wins: int = 0
    gambling_losses: int = 0
    peak_happiness: float = 0.0
    peak_happiness_cycle: int = 0
    lowest_happiness: float = 1.0
    lowest_happiness_cycle: int = 0
    narrative: str = ""


class LifeDirectoryWriter:
    """Generates and writes agent life directories."""

    def __init__(self, hive_dir: Path):
        self._hive_dir = hive_dir
        self._dir = hive_dir / "lives"
        self._dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        agent_id: str,
        identity_mgr: IdentityManager,
        stats_mgr: StatsManager,
        world: WorldState,
        event_engine: EventEngine,
        store: HiveStore,
        total_cycles: int = 0,
    ) -> LifeSummary:
        """Build a full life summary from all available data."""
        identity = identity_mgr.load(agent_id)
        stats = stats_mgr.get(agent_id)
        finances = world.get_finances(agent_id)
        skills = world.get_skills(agent_id)
        event_history = event_engine.get_history(agent_id)

        milestones = []
        gamble_count = 0
        gamble_wins = 0

        for outcome in event_history:
            milestone = LifeMilestone(
                cycle=outcome.cycle,
                description=f"{outcome.event_name}: chose '{outcome.choice_description}'",
                category=outcome.event_id,
                stat_snapshot=outcome.stat_changes,
            )
            milestones.append(milestone)

            if "gambling" in outcome.event_id or "bet" in outcome.choice_id:
                gamble_count += 1
                if outcome.stat_changes.get("money", 0) > 0:
                    gamble_wins += 1

        summary = LifeSummary(
            agent_id=agent_id,
            display_name=identity.display_name if identity else "",
            role=identity.domains[0] if identity and identity.domains else "",
            traits=identity.traits if identity else [],
            cycles_lived=stats.cycles_alive,
            final_stats={
                "happiness": stats.happiness,
                "health": stats.health,
                "reputation": stats.reputation,
                "energy": stats.energy,
            },
            final_money=finances.balance,
            milestones=milestones,
            skills_learned=[s.skill_name for s in skills],
            times_gambled=gamble_count,
            gambling_wins=gamble_wins,
            gambling_losses=gamble_count - gamble_wins,
            peak_happiness=stats.happiness,
            peak_happiness_cycle=stats.cycles_alive,
            lowest_happiness=stats.happiness,
            lowest_happiness_cycle=0,
            narrative=identity.full_narrative() if identity else "",
        )

        return summary

    def write(self, summary: LifeSummary) -> Path:
        """Write a life summary to the lives directory."""
        agent_dir = self._dir / summary.agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)

        summary_path = agent_dir / "summary.json"
        tmp = summary_path.with_suffix(".tmp")
        tmp.write_text(summary.model_dump_json(indent=2))
        tmp.rename(summary_path)

        bio_path = agent_dir / "biography.md"
        bio_path.write_text(self._render_biography(summary))

        return agent_dir

    def _render_biography(self, s: LifeSummary) -> str:
        """Render a human-readable biography markdown."""
        lines = [
            f"# Life of {s.display_name or s.agent_id}",
            "",
            f"**Role:** {s.role}",
            f"**Traits:** {', '.join(s.traits) if s.traits else 'none'}",
            f"**Lived:** {s.cycles_lived} cycles",
            "",
            "## Final Stats",
            "",
            f"- Money: ${s.final_money:.0f}",
        ]

        for stat, val in s.final_stats.items():
            lines.append(f"- {stat.title()}: {val:.0%}")

        if s.skills_learned:
            lines.extend(["", "## Skills", ""])
            for sk in s.skills_learned:
                lines.append(f"- {sk}")

        if s.milestones:
            lines.extend(["", "## Major Events", ""])
            for m in s.milestones:
                changes = ""
                if m.stat_snapshot:
                    parts = []
                    for k, v in m.stat_snapshot.items():
                        sign = "+" if v > 0 else ""
                        parts.append(f"{k}: {sign}{v}")
                    changes = f" ({', '.join(parts)})"
                lines.append(f"- **Cycle {m.cycle}:** {m.description}{changes}")

        lines.extend(
            [
                "",
                "## Statistics",
                "",
                f"- Goals completed: {s.goals_completed}",
                f"- Goals abandoned: {s.goals_abandoned}",
                f"- Times gambled: {s.times_gambled} "
                f"(won {s.gambling_wins}, lost {s.gambling_losses})",
            ]
        )

        if s.narrative:
            lines.extend(["", "## Agent's Own Narrative", "", s.narrative])

        lines.append("")
        return "\n".join(lines)

    def list_lives(self) -> list[str]:
        """List all agent IDs that have life directories."""
        if not self._dir.exists():
            return []
        return [d.name for d in self._dir.iterdir() if d.is_dir()]

    def read(self, agent_id: str) -> LifeSummary | None:
        """Read a previously written life summary."""
        path = self._dir / agent_id / "summary.json"
        if not path.exists():
            return None
        return LifeSummary.model_validate_json(path.read_text())

    def read_biography(self, agent_id: str) -> str:
        """Read the rendered biography markdown."""
        path = self._dir / agent_id / "biography.md"
        if not path.exists():
            return ""
        return path.read_text()
