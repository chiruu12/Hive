"""Detective demo — multi-model murder mystery investigation."""

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

SCENARIO_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scenarios" / "detective"


def extract_json(text: str) -> dict[str, Any] | None:
    """Extract JSON from model response, handling thinking tokens and markdown."""
    text = text.strip()
    md = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if md:
        text = md.group(1).strip()
    think = re.search(r"</think>\s*(.*)", text, re.DOTALL)
    if think:
        text = think.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed: dict[str, Any] = json.loads(text[start : end + 1])
            return parsed
        except json.JSONDecodeError:
            pass
    try:
        result: dict[str, Any] = json.loads(text)
        return result
    except json.JSONDecodeError:
        return None


DETECTIVES = [
    {
        "name": "Detective Sharp",
        "personality": "Methodical and evidence-driven. Follows logical chains.",
        "approach": "Start with physical evidence, build timeline, eliminate suspects.",
    },
    {
        "name": "Detective Reyes",
        "personality": "Intuitive and people-focused. Reads between the lines.",
        "approach": "Focus on motive and relationships. Who benefits?",
    },
    {
        "name": "Detective Park",
        "personality": "Creative and unconventional. Questions obvious conclusions.",
        "approach": "Look for what doesn't fit. The anomaly reveals the truth.",
    },
]


def run_detective_demo(model: str = "claude-haiku-4-5") -> None:
    """Run the detective scenario with Rich output."""
    console.print(
        Panel(
            "[bold]Hive Detective Demo[/bold]\n\n"
            "A murder at the Thornfield Gallery. 3 detectives investigate.\n"
            f"  Model: [green]{model}[/green]\n"
            "  Rounds: 4 + final accusation\n\n"
            "[dim]Each detective sees the crime scene, gets clues, and forms theories.[/dim]",
            border_style="blue",
            title="Detective",
        )
    )

    crime_scene = _load_crime_scene()
    if not crime_scene:
        console.print("[red]Crime scene files not found. Run from the repo root.[/red]")
        return

    clues = _load_clues()
    asyncio.run(_run_investigation(model, crime_scene, clues))


def _load_crime_scene() -> str:
    path = SCENARIO_DIR / "crime_scene.md"
    if not path.exists():
        return ""
    return path.read_text()


def _load_clues() -> list[str]:
    clues_dir = SCENARIO_DIR / "clues"
    if not clues_dir.exists():
        return []
    clue_files = sorted(clues_dir.glob("clue_*.md"))
    return [f.read_text() for f in clue_files]


async def _run_investigation(
    model: str, crime_scene: str, clues: list[str]
) -> None:
    from hive.models.factory import create_runtime_provider
    from hive.runtime.types import Message

    provider = create_runtime_provider(model)
    theories: dict[str, list[dict[str, Any]]] = {d["name"]: [] for d in DETECTIVES}
    rounds = min(4, len(clues)) if clues else 2

    for round_num in range(1, rounds + 1):
        console.print(f"\n[bold]--- Round {round_num} ---[/bold]")
        clue = clues[round_num - 1] if round_num <= len(clues) else ""

        for det in DETECTIVES:
            name = det["name"]
            console.print(f"  [cyan]{name}[/cyan] investigating...", end="")

            other_theories = ""
            for other_name, t_list in theories.items():
                if other_name != name and t_list:
                    latest = t_list[-1]
                    other_theories += (
                        f"\n{other_name} suspects: "
                        f"{latest.get('suspect', 'unknown')} "
                        f"({latest.get('confidence', '?')}% confidence)"
                    )

            prompt = (
                f"You are {name}, a detective. {det['personality']}\n"
                f"Approach: {det['approach']}\n\n"
                f"CRIME SCENE:\n{crime_scene}\n\n"
            )
            if clue:
                prompt += f"NEW EVIDENCE (Round {round_num}):\n{clue}\n\n"
            if other_theories:
                prompt += f"OTHER DETECTIVES' THEORIES:{other_theories}\n\n"
            prompt += (
                "Analyze the evidence. Respond with ONLY JSON:\n"
                '{"suspect": "name", "confidence": 0-100, '
                '"method": "how", "motive": "why", '
                '"reasoning": "your analysis"}'
            )

            try:
                result = await provider.generate(
                    messages=[Message.user(prompt)],
                    max_tokens=500,
                )
                parsed = extract_json(result.content)
                if parsed:
                    theories[name].append(parsed)
                    suspect = parsed.get("suspect", "unknown")
                    conf = parsed.get("confidence", "?")
                    console.print(
                        f" suspects [bold]{suspect}[/bold] ({conf}%)"
                    )
                else:
                    theories[name].append({"suspect": "unknown", "confidence": 0})
                    console.print(" [dim]could not parse response[/dim]")
            except Exception as e:
                console.print(f" [red]error: {e}[/red]")
                theories[name].append({"suspect": "unknown", "confidence": 0})

    console.print("\n[bold]--- Final Accusations ---[/bold]\n")
    table = Table(title="Investigation Results")
    table.add_column("Detective", style="cyan")
    table.add_column("Suspect", style="bold")
    table.add_column("Confidence")
    table.add_column("Method")
    table.add_column("Motive", max_width=30)

    for det in DETECTIVES:
        name = det["name"]
        final = theories[name][-1] if theories[name] else {}
        table.add_row(
            name,
            final.get("suspect", "unknown"),
            f"{final.get('confidence', 0)}%",
            final.get("method", "?"),
            (final.get("motive") or "?")[:30],
        )

    console.print(table)
