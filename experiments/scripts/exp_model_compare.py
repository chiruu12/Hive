"""Experiment 1: Model Comparison.

Do different models produce different agent personalities under identical conditions?
3 agents with identical Persona configs, different models, 50 cycles.
"""

from typing import Any

from rich.table import Table

from base import Experiment, console

IDENTICAL_AGENT = {
    "role": "General-purpose autonomous agent",
    "personality": ["balanced", "goal-oriented", "adaptable"],
    "persona": {
        "values": ["efficiency", "learning", "collaboration"],
        "fears": ["stagnation", "wasted effort"],
        "purpose": "Accomplish goals efficiently while growing skills",
        "risk_tolerance": 0.5,
        "social_drive": 0.5,
        "concentration": 0.8,
        "autonomy_level": 0.5,
        "happiness": 0.7,
    },
}

MODELS = [
    ("claude-haiku-4-5", "Anthropic Haiku"),
    ("gpt-5.4-nano", "OpenAI Nano"),
    ("groq:llama-3.1-8b-instant", "Groq Llama 8B"),
]


class ModelCompareExperiment(Experiment):
    name = "model-compare"
    description = "Compare model behavior under identical agent configs"

    def run(self) -> dict[str, Any]:
        agents = []
        for model_id, label in MODELS:
            agents.append({
                "name": label.lower().replace(" ", "-"),
                "role": IDENTICAL_AGENT["role"],
                "model": model_id,
            })

        self._spawn_agents(agents, economy=True)
        console.print(f"  Spawned {len(agents)} agents, running 50 cycles...")
        self._run_daemon(cycles=50, heartbeat=3)

        metrics = self._collect_agent_metrics()

        table = Table(title="Model Comparison Results")
        table.add_column("Model", style="cyan")
        table.add_column("Goals Done")
        table.add_column("Goals Failed")
        table.add_column("Happiness")
        table.add_column("Suffering")
        table.add_column("Journal Words")

        for aid, m in metrics.items():
            table.add_row(
                m["name"],
                str(m["goals_completed"]),
                str(m["goals_abandoned"]),
                f"{m['happiness']:.0%}",
                f"{m['suffering_load']:.0%}",
                str(m["journal_word_count"]),
            )

        console.print(table)
        return {"agents": metrics}


if __name__ == "__main__":
    ModelCompareExperiment().execute()
