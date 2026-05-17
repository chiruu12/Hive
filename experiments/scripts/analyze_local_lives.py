"""Analyze Local Lives experiment results.

Accepts one or more result JSON files. Merges sequential runs or reads
a single simultaneous run. Generates comparison tables, journal excerpts,
suffering trajectories, and an auto-generated story summary.

Usage:
    # Analyze simultaneous run
    python experiments/scripts/analyze_local_lives.py experiments/results/local-lives-*.json

    # Analyze sequential runs (one file per model)
    python experiments/scripts/analyze_local_lives.py \\
        experiments/results/local-lives-phi-*.json \\
        experiments/results/local-lives-liquid-*.json \\
        experiments/results/local-lives-qwen-*.json
"""

import json
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

EMOTION_WORDS = {
    "frustrated", "excited", "worried", "hopeful", "desperate",
    "curious", "satisfied", "confused", "angry", "grateful",
    "afraid", "proud", "lonely", "determined", "overwhelmed",
    "anxious", "relieved", "bitter", "inspired", "exhausted",
}


def load_results(paths: list[str]) -> dict[str, dict[str, Any]]:
    """Load and merge result files into a unified agent dict."""
    all_agents: dict[str, dict[str, Any]] = {}

    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            console.print(f"[red]File not found: {path}[/red]")
            continue

        data = json.loads(path.read_text())
        agents = data.get("results", {}).get("agents", {})

        for aid, metrics in agents.items():
            label = metrics.get("name", aid)
            model = metrics.get("model", "unknown")
            key = f"{label} ({model.split(':')[-1].split('/')[-1][:15]})"
            all_agents[key] = metrics

    return all_agents


def score_entry(text: str) -> int:
    """Score a journal entry by length + emotional content."""
    words = text.lower().split()
    emo_count = sum(1 for w in words if w.strip(".,!?;:'\"") in EMOTION_WORDS)
    return len(words) + emo_count * 5


def extract_best_entries(
    journal: str, top_n: int = 3
) -> list[str]:
    """Extract the most interesting journal entries."""
    entries = [
        e.strip()
        for e in journal.split("---")
        if e.strip() and len(e.strip()) > 15
    ]
    scored = [(score_entry(e), e) for e in entries]
    scored.sort(reverse=True)
    return [e for _, e in scored[:top_n]]


def print_comparison_table(agents: dict[str, dict[str, Any]]) -> None:
    """Print the main comparison table."""
    table = Table(title="Local Lives — Model Comparison", show_lines=True)
    table.add_column("Agent", style="cyan", min_width=20)
    table.add_column("Goals Done", justify="right")
    table.add_column("Failed", justify="right")
    table.add_column("Happiness", justify="right")
    table.add_column("Suffering", justify="right")
    table.add_column("Risk", justify="right")
    table.add_column("Concentration", justify="right")
    table.add_column("Journal Words", justify="right")

    for key, m in agents.items():
        table.add_row(
            key,
            str(m.get("goals_completed", 0)),
            str(m.get("goals_abandoned", 0)),
            f"{m.get('happiness', 0):.0%}",
            f"{m.get('suffering_load', 0):.0%}",
            f"{m.get('risk_tolerance', 0):.2f}",
            f"{m.get('concentration', 0):.2f}",
            str(m.get("journal_word_count", 0)),
        )

    console.print(table)


def print_journal_excerpts(agents: dict[str, dict[str, Any]]) -> None:
    """Print the best journal entry from each agent."""
    console.print("\n[bold]Best Journal Entries[/bold]\n")

    for key, m in agents.items():
        journal = m.get("journal_text", "")
        if not journal.strip():
            console.print(f"  [dim]{key}: no journal entries[/dim]")
            continue

        best = extract_best_entries(journal, top_n=1)
        if best:
            excerpt = best[0][:400]
            emo_words = [
                w for w in excerpt.lower().split()
                if w.strip(".,!?;:'\"") in EMOTION_WORDS
            ]
            emo_tag = f" [{len(emo_words)} emotional words]" if emo_words else ""
            console.print(
                Panel(
                    excerpt,
                    title=f"{key}{emo_tag}",
                    border_style="blue",
                )
            )


def print_story_summary(agents: dict[str, dict[str, Any]]) -> None:
    """Generate an auto-summary of what happened."""
    console.print("\n[bold]Story Summary[/bold]\n")

    if not agents:
        console.print("  [dim]No data to summarize.[/dim]")
        return

    ranked_happiness = sorted(
        agents.items(), key=lambda x: x[1].get("happiness", 0), reverse=True
    )
    ranked_suffering = sorted(
        agents.items(), key=lambda x: x[1].get("suffering_load", 0), reverse=True
    )
    ranked_goals = sorted(
        agents.items(),
        key=lambda x: x[1].get("goals_completed", 0),
        reverse=True,
    )

    happiest_name = ranked_happiness[0][0]
    happiest_val = ranked_happiness[0][1].get("happiness", 0)
    most_suffering_name = ranked_suffering[0][0]
    most_suffering_val = ranked_suffering[0][1].get("suffering_load", 0)
    most_productive_name = ranked_goals[0][0]
    most_productive_val = ranked_goals[0][1].get("goals_completed", 0)

    sentences = []
    sentences.append(
        f"{most_productive_name} was the most productive with "
        f"{most_productive_val} goals completed."
    )

    if most_suffering_name != most_productive_name:
        sentences.append(
            f"{most_suffering_name} suffered the most "
            f"(load: {most_suffering_val:.0%})."
        )

    if happiest_name != most_productive_name:
        sentences.append(
            f"{happiest_name} ended up happiest "
            f"(happiness: {happiest_val:.0%})."
        )

    least_happy = ranked_happiness[-1]
    if least_happy[1].get("happiness", 1) < 0.4:
        sentences.append(
            f"{least_happy[0]} struggled — happiness dropped to "
            f"{least_happy[1].get('happiness', 0):.0%}."
        )

    for key, m in agents.items():
        risk = m.get("risk_tolerance", 0.4)
        if risk > 0.7:
            sentences.append(
                f"{key}'s risk tolerance climbed to {risk:.0%} — "
                f"suffering pushed them toward desperate decisions."
            )

    story = " ".join(sentences)
    console.print(f"  {story}")


def main() -> None:
    if len(sys.argv) < 2:
        console.print(
            "[red]Usage: python analyze_local_lives.py "
            "results/local-lives-*.json[/red]"
        )
        sys.exit(1)

    paths = sys.argv[1:]
    console.print(
        Panel(
            f"[bold]Local Lives Analysis[/bold]\n"
            f"  Files: {len(paths)}\n"
            f"  {', '.join(Path(p).name for p in paths)}",
            border_style="green",
        )
    )

    agents = load_results(paths)

    if not agents:
        console.print("[red]No agent data found in result files.[/red]")
        sys.exit(1)

    print_comparison_table(agents)
    print_journal_excerpts(agents)
    print_story_summary(agents)


if __name__ == "__main__":
    main()
