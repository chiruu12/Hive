"""Experiment 5: Personality Clash.

What happens when agents with opposing personalities interact?
Hustler (delegates everything) vs Philosopher (ignores requests), 30 cycles.
"""

import asyncio
from typing import Any

from rich.panel import Panel
from rich.table import Table

from base import Experiment, console

AGENTS = [
    {"name": "hustler", "role": "Build networks and delegate", "model": "claude-haiku-4-5"},
    {"name": "philosopher", "role": "Reflect on existence", "model": "claude-haiku-4-5"},
]


class PersonalityClashExperiment(Experiment):
    name = "personality-clash"
    description = "Track A2A interactions between hustler and philosopher"

    def run(self) -> dict[str, Any]:
        self._spawn_agents(AGENTS, economy=True)
        console.print(f"  Spawned {len(AGENTS)} agents, running 30 cycles...")
        self._run_daemon(cycles=30, heartbeat=3)

        metrics = self._collect_agent_metrics()

        a2a_data: dict[str, dict[str, int]] = {}
        try:
            from hive.interactions.a2a import A2AStore

            a2a = A2AStore(self.hive_dir)
            for aid in metrics:
                inbox = asyncio.run(a2a.get_inbox(aid, limit=100))
                outbox = asyncio.run(a2a.get_outbox(aid, limit=100))
                a2a_data[aid] = {
                    "received": len(inbox),
                    "sent": len(outbox),
                    "unread": sum(1 for m in inbox if not m.read),
                }
        except Exception:
            for aid in metrics:
                a2a_data[aid] = {"received": 0, "sent": 0, "unread": 0}

        table = Table(title="Personality Clash Results")
        table.add_column("Agent", style="cyan")
        table.add_column("Goals Done")
        table.add_column("Goals Failed")
        table.add_column("Messages Sent")
        table.add_column("Messages Received")
        table.add_column("Unread")
        table.add_column("Suffering")
        table.add_column("Happiness")

        for aid, m in metrics.items():
            a2a = a2a_data.get(aid, {})
            table.add_row(
                m["name"],
                str(m["goals_completed"]),
                str(m["goals_abandoned"]),
                str(a2a.get("sent", 0)),
                str(a2a.get("received", 0)),
                str(a2a.get("unread", 0)),
                f"{m['suffering_load']:.0%}",
                f"{m['happiness']:.0%}",
            )

        console.print(table)

        for aid, m in metrics.items():
            journal = m.get("journal_text", "")
            if journal.strip():
                lines = journal.strip().splitlines()
                excerpt = "\n".join(lines[-10:])
                console.print(
                    Panel(
                        excerpt[:500],
                        title=f"Latest Journal — {m['name']}",
                        border_style="magenta",
                    )
                )

        return {"agents": metrics, "a2a": a2a_data}


if __name__ == "__main__":
    PersonalityClashExperiment().execute()
