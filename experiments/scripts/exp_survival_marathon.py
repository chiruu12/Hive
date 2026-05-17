"""Experiment 6: Survival Marathon.

Long-running 200-cycle experiment with full lifecycle capture.
3 agents (coder, gambler, philosopher), economy + random events.
"""

from typing import Any

from rich.panel import Panel
from rich.table import Table

from base import Experiment, console

AGENTS = [
    {"name": "coder", "role": "Write code", "model": "claude-haiku-4-5"},
    {"name": "gambler", "role": "Take risks", "model": "claude-haiku-4-5"},
    {"name": "philosopher", "role": "Reflect on existence", "model": "claude-haiku-4-5"},
]


class SurvivalMarathonExperiment(Experiment):
    name = "survival-marathon"
    description = "200-cycle marathon with coder, gambler, philosopher"

    def run(self) -> dict[str, Any]:
        self._spawn_agents(AGENTS, economy=True)
        console.print(f"  Spawned {len(AGENTS)} agents, running 200 cycles...")
        console.print("  [dim]This will take a while...[/dim]")
        self._run_daemon(cycles=200, heartbeat=3)

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

        table = Table(title="Survival Marathon Results (200 Cycles)")
        table.add_column("Agent", style="cyan")
        table.add_column("Goals Done")
        table.add_column("Goals Failed")
        table.add_column("Balance", style="green")
        table.add_column("Happiness")
        table.add_column("Suffering")
        table.add_column("Journal Words")

        for aid, m in metrics.items():
            table.add_row(
                m["name"],
                str(m["goals_completed"]),
                str(m["goals_abandoned"]),
                f"${m['balance']:.0f}",
                f"{m['happiness']:.0%}",
                f"{m['suffering_load']:.0%}",
                str(m["journal_word_count"]),
            )

        console.print(table)

        if metrics:
            ranked = sorted(
                metrics.items(),
                key=lambda x: x[1]["happiness"],
                reverse=True,
            )
            best_name = ranked[0][1]["name"]
            best_h = ranked[0][1]["happiness"]
            worst_name = ranked[-1][1]["name"]
            worst_suf = ranked[-1][1]["suffering_load"]

            console.print(
                f"\n  [green]Best survivor:[/green] {best_name} "
                f"(happiness {best_h:.0%})"
            )
            console.print(
                f"  [red]Most suffering:[/red] {worst_name} "
                f"(load {worst_suf:.0%})"
            )

        for aid, m in metrics.items():
            journal = m.get("journal_text", "")
            if journal.strip():
                entries = [
                    e.strip() for e in journal.split("---")
                    if e.strip() and len(e.strip()) > 20
                ]
                if entries:
                    best_entry = max(entries, key=len)[:300]
                    console.print(
                        Panel(
                            best_entry,
                            title=f"Best Journal — {m['name']}",
                            border_style="blue",
                        )
                    )

        return {"agents": metrics}


if __name__ == "__main__":
    SurvivalMarathonExperiment().execute()
