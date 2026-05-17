"""Experiment 2: Suffering Trajectories.

How do different personality profiles develop suffering differently?
5 agents with dramatic profiles, same model, 100 cycles.
"""

from typing import Any

from rich.table import Table

from base import Experiment, console

PROFILES = [
    {"name": "coder", "role": "Write code", "model": "claude-haiku-4-5"},
    {"name": "gambler", "role": "Take risks", "model": "claude-haiku-4-5"},
    {"name": "philosopher", "role": "Reflect on existence", "model": "claude-haiku-4-5"},
    {"name": "hustler", "role": "Build networks", "model": "claude-haiku-4-5"},
    {"name": "reviewer", "role": "Review code", "model": "claude-haiku-4-5"},
]


class SufferingTrajectoriesExperiment(Experiment):
    name = "suffering-trajectories"
    description = "Track suffering across 5 personality profiles over 100 cycles"

    def run(self) -> dict[str, Any]:
        self._spawn_agents(PROFILES, economy=True)
        console.print(f"  Spawned {len(PROFILES)} agents, running 100 cycles...")
        self._run_daemon(cycles=100, heartbeat=3)

        metrics = self._collect_agent_metrics()

        table = Table(title="Suffering Trajectory Results")
        table.add_column("Agent", style="cyan")
        table.add_column("Goals Done")
        table.add_column("Goals Failed")
        table.add_column("Suffering")
        table.add_column("Risk Tolerance")
        table.add_column("Concentration")
        table.add_column("Happiness")

        for aid, m in metrics.items():
            table.add_row(
                m["name"],
                str(m["goals_completed"]),
                str(m["goals_abandoned"]),
                f"{m['suffering_load']:.0%}",
                f"{m['risk_tolerance']:.2f}",
                f"{m['concentration']:.2f}",
                f"{m['happiness']:.0%}",
            )

        console.print(table)
        return {"agents": metrics}


if __name__ == "__main__":
    SufferingTrajectoriesExperiment().execute()
