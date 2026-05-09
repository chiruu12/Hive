"""Built-in toolkits for the Hive world simulation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from hive.runtime.tools import Toolkit, tool

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
                f"Balance: ${fin.balance}, "
                f"Earned: ${fin.total_earned}, Spent: ${fin.total_spent}"
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


class MemoryToolkit(Toolkit):
    """Agent-scoped key-value memory stored as JSON files."""

    def __init__(self, memory_dir: Path, agent_id: str):
        self._path = memory_dir / f"{agent_id}.json"
        self._agent_id = agent_id
        memory_dir.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text())

    def _save(self, data: dict[str, str]) -> None:
        self._path.write_text(json.dumps(data, indent=2))

    @tool()
    def memory_get(self, key: str) -> str:
        """Retrieve a previously stored value from your memory.

        Args:
            key: The key to look up.
        """
        data = self._load()
        value = data.get(key)
        if value is None:
            return f"Key not found: {key}. Available keys: {', '.join(data.keys()) or 'none'}"
        return str(value)

    @tool()
    def memory_set(self, key: str, value: str) -> str:
        """Store a value in your persistent memory for later retrieval.

        Args:
            key: The key to store under.
            value: The value to store.
        """
        data = self._load()
        data[key] = value
        self._save(data)
        return f"Stored: {key}"


class CommsToolkit(Toolkit):
    """Inter-agent messaging via inbox files."""

    def __init__(self, comms_dir: Path, agent_id: str):
        self._comms_dir = comms_dir
        self._agent_id = agent_id
        comms_dir.mkdir(parents=True, exist_ok=True)

    @tool()
    def send_message(self, target_agent: str, message: str) -> str:
        """Send a message to another agent.

        Args:
            target_agent: The ID of the agent to message.
            message: The message content.
        """
        inbox = self._comms_dir / f"{target_agent}_inbox.jsonl"
        entry = json.dumps(
            {
                "from": self._agent_id,
                "message": message,
                "ts": datetime.now(UTC).isoformat(),
            }
        )
        with open(inbox, "a") as f:
            f.write(entry + "\n")
        return f"Sent to {target_agent}"

    @tool()
    def read_inbox(self) -> str:
        """Read all messages in your inbox from other agents."""
        inbox = self._comms_dir / f"{self._agent_id}_inbox.jsonl"
        if not inbox.exists():
            return "No messages."
        lines = inbox.read_text().strip().splitlines()
        if not lines:
            return "No messages."
        messages = []
        for line in lines:
            try:
                msg = json.loads(line)
                messages.append(f"[{msg.get('ts', '?')}] {msg['from']}: {msg['message']}")
            except json.JSONDecodeError:
                continue
        return "\n".join(messages) if messages else "No messages."
