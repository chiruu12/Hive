"""Detective scenario runner — three agents investigate a murder."""

import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

SCENARIO_DIR = Path(__file__).parent
CLUES_DIR = SCENARIO_DIR / "clues"

sys.path.insert(0, str(SCENARIO_DIR.parent.parent))

import re

from hive.config import load_config
from hive.runtime.providers import create_runtime_provider
from hive.runtime.types import Message


def extract_json(text: str) -> dict | None:
    """Extract JSON from model response, handling thinking tokens and markdown."""
    text = text.strip()
    # Strip markdown code blocks
    md = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if md:
        text = md.group(1).strip()
    # Strip thinking tokens (common in qwen/deepseek)
    think = re.search(r"</think>\s*(.*)", text, re.DOTALL)
    if think:
        text = think.group(1).strip()
    # Find first { to last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    # Try the whole thing
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def load_crime_scene() -> str:
    return (SCENARIO_DIR / "crime_scene.md").read_text()


def load_clues() -> dict[str, str]:
    clues = {}
    for f in sorted(CLUES_DIR.glob("clue_*.md")):
        clues[f.stem] = f.read_text()
    return clues


def load_config_yaml() -> dict:
    return yaml.safe_load((SCENARIO_DIR / "config.yaml").read_text())


async def investigate(
    detective: dict,
    crime_scene: str,
    clues: dict[str, str],
    round_num: int,
    other_theories: list[str],
) -> dict:
    """One round of investigation for one detective."""
    provider = create_runtime_provider(detective["model"])

    system = (
        f"You are {detective['display_name']}, a detective investigating a murder.\n"
        f"Personality: {detective['personality']}\n"
        f"Approach: {detective['approach']}\n"
        "Stay in character. Be specific about evidence. Think step by step."
    )

    available_clues = list(clues.keys())[: 2 + round_num * 2]
    clue_text = "\n\n---\n\n".join(clues[k] for k in available_clues)

    prompt_parts = [
        f"## Crime Scene\n{crime_scene}",
        f"\n## Evidence (Round {round_num + 1})\n{clue_text}",
    ]

    if other_theories:
        prompt_parts.append(
            "\n## Other Detectives' Theories\n" + "\n".join(f"- {t}" for t in other_theories)
        )

    prompt_parts.append(
        "\n## Your Task\n"
        "Based on the evidence so far:\n"
        "1. What is your current theory?\n"
        "2. Who is your prime suspect and why?\n"
        "3. What evidence do you still need?\n\n"
        "Respond as JSON:\n"
        '{"theory": "your theory in 2-3 sentences", '
        '"prime_suspect": "name", '
        '"confidence": 0.0-1.0, '
        '"reasoning": "key evidence points", '
        '"need": "what you still need to check"}\n'
    )

    prompt = "\n".join(prompt_parts)

    try:
        response = await provider.generate_with_metadata(
            messages=[
                Message.system(system),
                Message.user(prompt),
            ],
            max_tokens=2048,
        )

        result = extract_json(response.message.content)
        if not result:
            result = {
                "theory": response.message.content[:200],
                "prime_suspect": "unknown",
                "confidence": 0.3,
                "reasoning": "Could not parse structured response",
                "need": "more evidence",
            }

        result["detective"] = detective["display_name"]
        result["model"] = detective["model"]
        result["round"] = round_num + 1
        result["tokens"] = response.input_tokens + response.output_tokens
        result["cost_usd"] = response.cost_usd or 0.0
        result["duration_ms"] = response.duration_ms or 0

        return result

    except Exception as e:
        logger.error("Detective %s failed: %s", detective["display_name"], e)
        return {
            "detective": detective["display_name"],
            "model": detective["model"],
            "round": round_num + 1,
            "theory": f"Investigation failed: {e}",
            "prime_suspect": "unknown",
            "confidence": 0.0,
            "reasoning": str(e),
            "need": "retry",
            "tokens": 0,
            "cost_usd": 0.0,
            "duration_ms": 0,
        }


async def final_accusation(detective: dict, crime_scene: str, clues: dict[str, str]) -> dict:
    """Each detective makes their final accusation."""
    provider = create_runtime_provider(detective["model"])

    all_clues = "\n\n---\n\n".join(clues.values())

    prompt = (
        f"## Crime Scene\n{crime_scene}\n\n"
        f"## All Evidence\n{all_clues}\n\n"
        "## Final Accusation\n"
        "You must now make your final accusation. Who killed Marcus Thornfield?\n"
        "Explain the method, motive, and how the locked room was achieved.\n\n"
        "Respond as JSON:\n"
        '{"killer": "name", "method": "how they did it", '
        '"motive": "why", "locked_room": "how the locked room was achieved", '
        '"confidence": 0.0-1.0}\n'
    )

    system = (
        f"You are {detective['display_name']}.\n"
        f"Personality: {detective['personality']}\n"
        "Make your final accusation based on ALL evidence. Be decisive."
    )

    response = await provider.generate_with_metadata(
        messages=[
            Message.system(system),
            Message.user(prompt),
        ],
        max_tokens=2048,
    )

    result = extract_json(response.message.content)
    if not result:
        result = {
            "killer": "unknown",
            "method": response.message.content[:200],
            "motive": "unknown",
            "locked_room": "unknown",
            "confidence": 0.3,
        }

    result["detective"] = detective["display_name"]
    result["model"] = detective["model"]
    result["tokens"] = response.input_tokens + response.output_tokens
    result["cost_usd"] = response.cost_usd or 0.0

    return result


def print_separator():
    print("=" * 70)


async def run_scenario():
    """Run the full detective scenario."""
    config = load_config_yaml()
    crime_scene = load_crime_scene()
    clues = load_clues()

    load_config(Path.cwd() / ".hive" if (Path.cwd() / ".hive").exists() else None)

    print_separator()
    print(f"  {config['name']}")
    print(f"  {config['description']}")
    print_separator()
    print()

    detectives = config["detectives"]
    rounds = config.get("rounds", 4)
    all_results: list[list[dict]] = []
    total_tokens = 0
    total_cost = 0.0

    for r in range(rounds):
        print(f"\n--- ROUND {r + 1} of {rounds} ---\n")

        other_theories = []
        if all_results:
            for prev in all_results[-1]:
                other_theories.append(
                    f"{prev['detective']}: suspects {prev['prime_suspect']} "
                    f"({prev['confidence']:.0%} confident)"
                )

        round_results = []
        for det in detectives:
            print(f"  {det['display_name']} ({det['model'].split('/')[-1]}) investigating...")
            result = await investigate(det, crime_scene, clues, r, other_theories)
            round_results.append(result)

            total_tokens += result.get("tokens", 0)
            total_cost += result.get("cost_usd", 0)

            print(
                f"    Suspects: {result['prime_suspect']} "
                f"({result.get('confidence', 0):.0%} confident)"
            )
            print(f"    Theory: {result.get('theory', '?')[:100]}")
            print(f"    [{result.get('tokens', 0)} tokens, ${result.get('cost_usd', 0):.4f}]")
            print()

        all_results.append(round_results)

    if config.get("final_accusation"):
        print_separator()
        print("  FINAL ACCUSATIONS")
        print_separator()
        print()

        accusations = []
        for det in detectives:
            print(f"  {det['display_name']} making final accusation...")
            result = await final_accusation(det, crime_scene, clues)
            accusations.append(result)

            total_tokens += result.get("tokens", 0)
            total_cost += result.get("cost_usd", 0)

            print(f"    ACCUSES: {result.get('killer', '?')}")
            print(f"    Method: {result.get('method', '?')[:100]}")
            print(f"    Motive: {result.get('motive', '?')[:100]}")
            print(f"    Locked room: {result.get('locked_room', '?')[:100]}")
            print(f"    Confidence: {result.get('confidence', 0):.0%}")
            print()

        print_separator()
        print("  RESULTS")
        print_separator()
        correct_answer = "Petra Novak"
        for acc in accusations:
            killer = acc.get("killer", "").lower()
            correct = "petra" in killer or "novak" in killer
            icon = "CORRECT" if correct else "WRONG"
            print(
                f"  {acc['detective']:20s} accused {acc.get('killer', '?'):20s} "
                f"[{icon}] ({acc['model'].split('/')[-1]})"
            )

    print()
    print_separator()
    print(f"  Total tokens: {total_tokens:,}")
    print(f"  Total cost: ${total_cost:.4f}")
    print_separator()

    results_dir = SCENARIO_DIR / "results"
    results_dir.mkdir(exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    results_path = results_dir / f"run-{ts}.json"
    results_path.write_text(
        json.dumps(
            {
                "scenario": config["name"],
                "timestamp": ts,
                "rounds": all_results,
                "accusations": accusations if config.get("final_accusation") else [],
                "total_tokens": total_tokens,
                "total_cost_usd": total_cost,
                "correct_answer": "Petra Novak",
            },
            indent=2,
        )
    )
    print(f"\n  Results saved to: {results_path}")


if __name__ == "__main__":
    asyncio.run(run_scenario())
