"""Experiment 4: Journal Quality.

What do agents actually write when given a journal? Is it interesting?
3 agents with journal preset, 50 cycles.
"""

from typing import Any

from rich.panel import Panel
from rich.table import Table

from base import Experiment, console

EMOTION_WORDS = {
    "frustrated", "excited", "worried", "hopeful", "desperate",
    "curious", "satisfied", "confused", "angry", "grateful",
    "afraid", "proud", "lonely", "determined", "overwhelmed",
    "anxious", "relieved", "bitter", "inspired", "exhausted",
}

AGENTS = [
    {"name": "coder", "role": "Write code", "model": "claude-haiku-4-5"},
    {"name": "philosopher", "role": "Reflect on existence", "model": "claude-haiku-4-5"},
    {"name": "gambler", "role": "Take risks", "model": "claude-haiku-4-5"},
]


class JournalQualityExperiment(Experiment):
    name = "journal-quality"
    description = "Analyze what agents write in their journals over 50 cycles"

    def run(self) -> dict[str, Any]:
        self._spawn_agents(AGENTS, economy=True)
        console.print(f"  Spawned {len(AGENTS)} agents, running 50 cycles...")
        self._run_daemon(cycles=50, heartbeat=3)

        metrics = self._collect_agent_metrics()
        all_entries: dict[str, dict[str, Any]] = {}

        for aid, m in metrics.items():
            journal = m.get("journal_text", "")
            words = journal.split() if journal.strip() else []
            total_words = len(words)
            unique_words = len(set(w.lower() for w in words))
            diversity = unique_words / max(total_words, 1)

            emotional = [
                w for w in words
                if w.lower().strip(".,!?;:") in EMOTION_WORDS
            ]

            entries = [
                e.strip()
                for e in journal.split("---")
                if e.strip() and len(e.strip()) > 10
            ]

            scored_entries = []
            for entry in entries:
                entry_words = entry.lower().split()
                emo_count = sum(
                    1 for w in entry_words
                    if w.strip(".,!?;:") in EMOTION_WORDS
                )
                scored_entries.append((len(entry_words) + emo_count * 5, entry))
            scored_entries.sort(reverse=True)
            top_entries = [e for _, e in scored_entries[:5]]

            all_entries[aid] = {
                "name": m["name"],
                "total_entries": len(entries),
                "total_words": total_words,
                "unique_words": unique_words,
                "vocabulary_diversity": diversity,
                "emotional_word_count": len(emotional),
                "top_entries": top_entries,
            }

        table = Table(title="Journal Quality Metrics")
        table.add_column("Agent", style="cyan")
        table.add_column("Entries")
        table.add_column("Words")
        table.add_column("Vocab Diversity")
        table.add_column("Emotional Words")

        for aid, info in all_entries.items():
            table.add_row(
                info["name"],
                str(info["total_entries"]),
                str(info["total_words"]),
                f"{info['vocabulary_diversity']:.0%}",
                str(info["emotional_word_count"]),
            )

        console.print(table)

        for aid, info in all_entries.items():
            if info["top_entries"]:
                best = info["top_entries"][0][:300]
                console.print(
                    Panel(
                        best,
                        title=f"Best Entry — {info['name']}",
                        border_style="blue",
                    )
                )

        return {"agents": all_entries}


if __name__ == "__main__":
    JournalQualityExperiment().execute()
