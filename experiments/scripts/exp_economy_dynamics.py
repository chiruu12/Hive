"""Experiment 3: Economy Dynamics.

Which personality profiles make money? Which go bankrupt?
5 agents, economy enabled, 100 cycles.
"""

import asyncio
from typing import Any

from rich.table import Table

from base import Experiment, console

PROFILES = [
    {"name": "coder", "role": "Write code", "model": "claude-haiku-4-5"},
    {"name": "gambler", "role": "Take risks", "model": "claude-haiku-4-5"},
    {"name": "philosopher", "role": "Reflect on existence", "model": "claude-haiku-4-5"},
    {"name": "hustler", "role": "Build networks", "model": "claude-haiku-4-5"},
    {"name": "researcher", "role": "Explore and document", "model": "claude-haiku-4-5"},
]


class EconomyDynamicsExperiment(Experiment):
    name = "economy-dynamics"
    description = "Track economic outcomes across 5 personality profiles"

    def run(self) -> dict[str, Any]:
        self._spawn_agents(PROFILES, economy=True)
        console.print(f"  Spawned {len(PROFILES)} agents, running 100 cycles...")
        self._run_daemon(cycles=100, heartbeat=3)

        metrics = self._collect_agent_metrics()

        balances: dict[str, float] = {}
        try:
            from hive.world.state import WorldState

            world = WorldState(self.hive_dir)
            for aid in metrics:
                try:
                    fin = world.get_finances(aid)
                    balances[aid] = fin.balance
                except Exception:
                    balances[aid] = 0.0
        except Exception:
            pass

        for aid, m in metrics.items():
            m["balance"] = balances.get(aid, 0.0)

        sorted_agents = sorted(
            metrics.items(), key=lambda x: x[1]["balance"], reverse=True
        )

        table = Table(title="Economy Leaderboard (Richest to Poorest)")
        table.add_column("Rank", style="bold")
        table.add_column("Agent", style="cyan")
        table.add_column("Balance", style="green")
        table.add_column("Goals Done")
        table.add_column("Happiness")
        table.add_column("Journal Words")

        for rank, (aid, m) in enumerate(sorted_agents, 1):
            medal = {1: "\U0001f947", 2: "\U0001f948", 3: "\U0001f949"}.get(rank, str(rank))
            table.add_row(
                medal,
                m["name"],
                f"${m['balance']:.0f}",
                str(m["goals_completed"]),
                f"{m['happiness']:.0%}",
                str(m["journal_word_count"]),
            )

        console.print(table)
        return {"agents": metrics, "ranking": [a for a, _ in sorted_agents]}


if __name__ == "__main__":
    EconomyDynamicsExperiment().execute()
