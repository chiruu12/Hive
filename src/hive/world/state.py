"""World state — the economy, jobs, skills, and agent finances."""

import json
import random
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from hive.config import get_config


class AgentFinances(BaseModel):
    agent_id: str
    balance: float = 100.0
    total_earned: float = 0.0
    total_spent: float = 0.0


class Job(BaseModel):
    job_id: str
    title: str
    salary: float
    required_skills: list[str] = []
    holder: str | None = None


class SkillProgress(BaseModel):
    skill_name: str
    level: float = 0.0
    max_level: float = 1.0


class GamblingResult(BaseModel):
    game: str
    wager: float
    won: bool
    payout: float
    description: str


AVAILABLE_JOBS = [
    Job(job_id="analyst", title="Data Analyst", salary=50.0, required_skills=[]),
    Job(job_id="reviewer", title="Code Reviewer", salary=70.0, required_skills=["code_review"]),
    Job(job_id="researcher", title="Researcher", salary=40.0, required_skills=[]),
    Job(job_id="teacher", title="Teacher", salary=60.0, required_skills=["teaching"]),
    Job(
        job_id="architect",
        title="System Architect",
        salary=100.0,
        required_skills=["architecture"],
    ),
]


def _eco() -> Any:
    return get_config().economy


class WorldState:
    """Manages the economy, jobs, skills, and agent finances."""

    def __init__(self, hive_dir: Path):
        # Local import: registry imports Job/AVAILABLE_JOBS from this module.
        from hive.world.registry import JobRegistry

        self._state_path = hive_dir / "world_state.json"
        self._finances: dict[str, AgentFinances] = {}
        self._jobs: list[Job] = [j.model_copy() for j in JobRegistry.default().all()]
        self._skills: dict[str, list[SkillProgress]] = {}
        self._cycle_count = 0
        self._load()

    def _load(self) -> None:
        if self._state_path.exists():
            data = json.loads(self._state_path.read_text())
            for aid, fin in data.get("finances", {}).items():
                self._finances[aid] = AgentFinances(**fin)
            for j_data in data.get("jobs", []):
                for j in self._jobs:
                    if j.job_id == j_data.get("job_id"):
                        j.holder = j_data.get("holder")
            for aid, skills in data.get("skills", {}).items():
                self._skills[aid] = [SkillProgress(**s) for s in skills]

    def _save(self) -> None:
        data = {
            "finances": {aid: f.model_dump() for aid, f in self._finances.items()},
            "jobs": [j.model_dump() for j in self._jobs],
            "skills": {
                aid: [s.model_dump() for s in skills] for aid, skills in self._skills.items()
            },
            "cycle": self._cycle_count,
        }
        self._state_path.write_text(json.dumps(data, indent=2))

    def get_finances(self, agent_id: str) -> AgentFinances:
        if agent_id not in self._finances:
            self._finances[agent_id] = AgentFinances(
                agent_id=agent_id,
                balance=_eco().starting_balance,
            )
        return self._finances[agent_id]

    def adjust_balance(self, agent_id: str, amount: float) -> None:
        """Adjust agent balance and persist. Use for event effects."""
        fin = self.get_finances(agent_id)
        fin.balance += amount
        if amount > 0:
            fin.total_earned += amount
        else:
            fin.total_spent += abs(amount)
        self._save()

    def get_skills(self, agent_id: str) -> list[SkillProgress]:
        return self._skills.get(agent_id, [])

    def has_skill(self, agent_id: str, skill_name: str) -> bool:
        for s in self.get_skills(agent_id):
            if s.skill_name == skill_name and s.level >= 0.5:
                return True
        return False

    def available_jobs(self) -> list[Job]:
        return [j for j in self._jobs if j.holder is None]

    def agent_job(self, agent_id: str) -> Job | None:
        for j in self._jobs:
            if j.holder == agent_id:
                return j
        return None

    def apply_job(self, agent_id: str, job_id: str) -> str:
        job = next((j for j in self._jobs if j.job_id == job_id), None)
        if not job:
            return f"Job not found: {job_id}"
        if job.holder is not None:
            return f"Job already taken: {job.title}"
        for req in job.required_skills:
            if not self.has_skill(agent_id, req):
                return f"Missing required skill: {req}"
        if self.agent_job(agent_id):
            return "Already employed. Quit first."
        job.holder = agent_id
        self._save()
        return f"Hired as {job.title} (${job.salary}/cycle)"

    def quit_job(self, agent_id: str) -> str:
        job = self.agent_job(agent_id)
        if not job:
            return "Not employed"
        job.holder = None
        self._save()
        return f"Quit {job.title}"

    def work(self, agent_id: str) -> str:
        job = self.agent_job(agent_id)
        if not job:
            return "Not employed. Apply for a job first."
        fin = self.get_finances(agent_id)
        fin.balance += job.salary
        fin.total_earned += job.salary
        self._save()
        return f"Worked as {job.title}. Earned ${job.salary}. Balance: ${fin.balance}"

    def learn(self, agent_id: str, skill_name: str) -> str:
        if skill_name not in _eco().learnable_skills:
            return f"Unknown skill: {skill_name}. Available: {', '.join(_eco().learnable_skills)}"
        fin = self.get_finances(agent_id)
        if fin.balance < _eco().skill_course_cost:
            return f"Not enough money. Need ${_eco().skill_course_cost}, have ${fin.balance}"
        fin.balance -= _eco().skill_course_cost
        fin.total_spent += _eco().skill_course_cost

        skills = self._skills.setdefault(agent_id, [])
        existing = next((s for s in skills if s.skill_name == skill_name), None)
        if existing:
            existing.level = min(existing.max_level, existing.level + _eco().skill_increment)
            level = existing.level
        else:
            sp = SkillProgress(skill_name=skill_name, level=_eco().skill_increment)
            skills.append(sp)
            level = sp.level

        self._save()
        return f"Studied {skill_name}. Level: {level:.0%}. Balance: ${fin.balance}"

    def gamble(self, agent_id: str, game: str, wager: float) -> GamblingResult:
        fin = self.get_finances(agent_id)
        wager = min(wager, fin.balance)
        if wager <= 0:
            return GamblingResult(
                game=game,
                wager=0,
                won=False,
                payout=0,
                description="No money to gamble",
            )

        fin.balance -= wager
        fin.total_spent += wager

        if game == "lottery":
            won = random.random() < _eco().lottery_win_chance
            payout = _eco().lottery_payout if won else 0
        else:
            won = random.random() < _eco().blackjack_win_rate
            payout = wager * 2 if won else 0

        if won:
            fin.balance += payout
            fin.total_earned += payout

        self._save()
        return GamblingResult(
            game=game,
            wager=wager,
            won=won,
            payout=payout,
            description=(
                f"{'Won' if won else 'Lost'} ${wager} on {game}. "
                f"{'Payout: $' + str(payout) + '.' if won else ''} "
                f"Balance: ${fin.balance}"
            ),
        )

    def get_status(self, agent_id: str) -> str:
        fin = self.get_finances(agent_id)
        job = self.agent_job(agent_id)
        skills = self.get_skills(agent_id)
        skill_strs = [f"{s.skill_name} ({s.level:.0%})" for s in skills]
        return (
            f"Balance: ${fin.balance}\n"
            f"Job: {job.title if job else 'unemployed'}"
            f"{' ($' + str(job.salary) + '/cycle)' if job else ''}\n"
            f"Skills: {', '.join(skill_strs) if skill_strs else 'none'}\n"
            f"Lifetime earned: ${fin.total_earned} | spent: ${fin.total_spent}"
        )

    def get_market_summary(self) -> str:
        lines = ["Available jobs:"]
        for j in self.available_jobs():
            reqs = f" (requires: {', '.join(j.required_skills)})" if j.required_skills else ""
            lines.append(f"  - {j.title}: ${j.salary}/cycle{reqs}")
        lines.append(f"\nSkill courses: ${_eco().skill_course_cost} each")
        lines.append(f"Skills: {', '.join(_eco().learnable_skills)}")
        lines.append("\nGambling:")
        lines.append(
            f"  - Lottery: ${_eco().lottery_cost} ticket, "
            f"{_eco().lottery_win_chance:.0%} chance of ${_eco().lottery_payout}"
        )
        lines.append(f"  - Blackjack: variable wager, {_eco().blackjack_win_rate:.0%} win rate")
        return "\n".join(lines)
