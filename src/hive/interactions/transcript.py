"""Transcript — records everything for replay and analysis."""

import json
from datetime import UTC, datetime
from pathlib import Path

from hive.interactions.base import RoundResult


class Transcript:
    """Records all messages and actions for a scenario run."""

    def __init__(self, output_dir: Path | None = None):
        self._dir = output_dir
        self._rounds: list[RoundResult] = []

    def add_round(self, result: RoundResult) -> None:
        self._rounds.append(result)

    def save(self, scenario_name: str) -> str:
        if not self._dir:
            return ""
        self._dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        path = self._dir / f"{scenario_name}-{ts}.json"

        data = {
            "scenario": scenario_name,
            "timestamp": ts,
            "rounds": [r.model_dump() for r in self._rounds],
            "total_messages": sum(len(r.messages) for r in self._rounds),
        }
        path.write_text(json.dumps(data, indent=2, default=str))
        return str(path)

    def render_text(self) -> str:
        """Render a human-readable transcript."""
        lines = []
        for rr in self._rounds:
            lines.append(f"\n--- Round {rr.round_num} ---")
            if rr.evidence_revealed:
                lines.append(f"  [EVIDENCE] {rr.evidence_revealed[:200]}")
            for m in rr.messages:
                prefix = m.sender
                if m.recipient != "all":
                    prefix += f" → {m.recipient}"
                lines.append(f"  {prefix}: {m.content[:200]}")
        return "\n".join(lines)
