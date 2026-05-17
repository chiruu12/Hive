"""World economy toolkit for agent interaction with the Hive simulation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from hive.tools.base import Toolkit, tool

if TYPE_CHECKING:
    from hive.world.state import WorldState


class WorldToolkit(Toolkit):
    """Tools for interacting with the Hive world economy."""

    def __init__(self, world: WorldState, agent_id: str):
        self._world = world
        self._agent_id = agent_id

    @tool()
    def work(self) -> str:
        """Perform your current job to earn salary. Must be employed first."""
        return self._world.work(self._agent_id)

    @tool()
    def apply_job(self, job_id: str) -> str:
        """Apply for a job by its ID. Must not already be employed.

        Args:
            job_id: The ID of the job to apply for.
        """
        return self._world.apply_job(self._agent_id, job_id)

    @tool()
    def quit_job(self) -> str:
        """Quit your current job."""
        return self._world.quit_job(self._agent_id)

    @tool()
    def learn(self, skill_name: str) -> str:
        """Study a skill to improve your qualifications. Costs money.

        Args:
            skill_name: The skill to learn.
        """
        return self._world.learn(self._agent_id, skill_name)

    @tool()
    def gamble(
        self,
        game: Literal["blackjack", "lottery"] = "blackjack",
        wager: float = 10.0,
    ) -> str:
        """Place a bet on a game of chance.

        Args:
            game: The game to play.
            wager: Amount of money to wager.
        """
        result = self._world.gamble(self._agent_id, game, wager)
        return result.description

    @tool()
    def query_world(
        self,
        query_type: Literal["jobs", "skills", "finances", "status", "market"] = "status",
    ) -> str:
        """Query the world state for information.

        Args:
            query_type: What to query — jobs, skills, finances, status, or market overview.
        """
        if query_type == "status":
            return self._world.get_status(self._agent_id)
        if query_type == "market":
            return self._world.get_market_summary()
        if query_type == "finances":
            fin = self._world.get_finances(self._agent_id)
            return (
                f"Balance: ${fin.balance}, Earned: ${fin.total_earned}, Spent: ${fin.total_spent}"
            )
        if query_type == "jobs":
            jobs = self._world.available_jobs()
            if not jobs:
                return "No jobs available."
            lines = [
                f"- {j.title} (${j.salary}/cycle, "
                f"requires: {', '.join(j.required_skills) or 'none'})"
                for j in jobs
            ]
            return "Available jobs:\n" + "\n".join(lines)
        if query_type == "skills":
            skills = self._world.get_skills(self._agent_id)
            if not skills:
                return "No skills learned yet."
            return "\n".join(f"- {s.skill_name}: {s.level:.0%}" for s in skills)
        return "Unknown query type"
