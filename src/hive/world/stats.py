"""Agent stats — happiness, health, reputation, energy beyond just money."""

import json
from pathlib import Path

from pydantic import BaseModel


class AgentStats(BaseModel):
    agent_id: str
    happiness: float = 0.5
    health: float = 0.8
    reputation: float = 0.5
    energy: float = 1.0
    cycles_alive: int = 0

    def apply(self, stat: str, change: float, change_type: str = "absolute") -> float:
        """Apply a stat change. Returns the new value."""
        current = getattr(self, stat, None)
        if current is None:
            return 0.0
        if change_type == "percent":
            new_val = current * (1 + change / 100)
        else:
            new_val = current + change
        new_val = max(0.0, min(1.0, new_val))
        setattr(self, stat, new_val)
        return new_val

    def tick(self) -> None:
        """Called each daemon cycle. Energy recovers, cycles increment."""
        self.cycles_alive += 1
        self.energy = min(1.0, self.energy + 0.05)

    def summary_line(self) -> str:
        return (
            f"HP:{self.health:.0%} "
            f"😊:{self.happiness:.0%} "
            f"⭐:{self.reputation:.0%} "
            f"⚡:{self.energy:.0%}"
        )


class StatsManager:
    """Persist and manage stats for all agents."""

    def __init__(self, hive_dir: Path):
        self._path = hive_dir / "agent_stats.json"
        self._stats: dict[str, AgentStats] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            for aid, s in data.items():
                self._stats[aid] = AgentStats(**s)
        except (json.JSONDecodeError, ValueError):
            pass

    def _save(self) -> None:
        data = {aid: s.model_dump() for aid, s in self._stats.items()}
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.rename(self._path)

    def get(self, agent_id: str) -> AgentStats:
        if agent_id not in self._stats:
            self._stats[agent_id] = AgentStats(agent_id=agent_id)
        return self._stats[agent_id]

    def apply_effect(
        self, agent_id: str, stat: str, change: float, change_type: str = "absolute"
    ) -> float:
        stats = self.get(agent_id)
        if stat == "money":
            return change
        result = stats.apply(stat, change, change_type)
        self._save()
        return result

    def tick(self, agent_id: str) -> None:
        stats = self.get(agent_id)
        stats.tick()
        self._save()

    def get_all(self) -> dict[str, AgentStats]:
        return dict(self._stats)
