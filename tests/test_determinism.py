"""Deterministic mode: seedable world RNG + run manifest."""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

from hive.config import HiveConfig
from hive.logging.writer import LogWriter
from hive.world.event_engine import EventEngine
from hive.world.events import Choice, LifeEvent, StatEffect
from hive.world.state import WorldState
from hive.world.stats import StatsManager


def _engine(tmp_path: Path, name: str, seed: int) -> EventEngine:
    root = tmp_path / name
    root.mkdir()
    stats = StatsManager(root)
    stats.get("agent-1").cycles_alive = 50  # make most events eligible
    world = WorldState(root, rng=random.Random(seed))
    return EventEngine(stats, world, root, rng=random.Random(seed))


class TestWorldRngSeeding:
    def test_event_rolls_reproducible(self, tmp_path: Path) -> None:
        a = _engine(tmp_path, "a", 42)
        b = _engine(tmp_path, "b", 42)
        rolls_a = [[e.event_id for e in a.roll_events("agent-1", c)] for c in range(1, 40)]
        rolls_b = [[e.event_id for e in b.roll_events("agent-1", c)] for c in range(1, 40)]
        assert rolls_a == rolls_b
        # And something actually fired, so we're not just comparing empty lists.
        assert any(rolls_a)

    def test_different_seeds_diverge(self, tmp_path: Path) -> None:
        a = _engine(tmp_path, "a", 42)
        b = _engine(tmp_path, "b", 7)
        rolls_a = [[e.event_id for e in a.roll_events("agent-1", c)] for c in range(1, 40)]
        rolls_b = [[e.event_id for e in b.roll_events("agent-1", c)] for c in range(1, 40)]
        assert rolls_a != rolls_b

    def test_luck_reproducible(self, tmp_path: Path) -> None:
        event = LifeEvent(
            event_id="windfall",
            name="Windfall",
            description="!",
            category="luck",
            choices=[
                Choice(
                    id="take",
                    description="Take it",
                    stat_effects=[StatEffect(stat="money", change=100)],
                )
            ],
        )
        a = _engine(tmp_path, "la", 99)
        b = _engine(tmp_path, "lb", 99)
        out_a = a.apply_choice("agent-1", event, "take", cycle=1)
        out_b = b.apply_choice("agent-1", event, "take", cycle=1)
        # Luck is applied to the money effect; same seed -> same outcome.
        assert out_a.stat_changes["money"] == out_b.stat_changes["money"]

    def test_gambling_reproducible(self, tmp_path: Path) -> None:
        def play(name: str, seed: int) -> list[bool]:
            root = tmp_path / name
            root.mkdir()
            world = WorldState(root, rng=random.Random(seed))
            world.adjust_balance("agent-1", 10_000)
            return [world.gamble("agent-1", "blackjack", 1).won for _ in range(25)]

        assert play("g1", 5) == play("g2", 5)


class TestSeedConfig:
    def test_default_is_none(self) -> None:
        assert HiveConfig().seed is None

    def test_loads_from_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "config.yaml").write_text("seed: 1234\n")
        assert HiveConfig.load(tmp_path).seed == 1234

    def test_env_override(self, tmp_path: Path) -> None:
        os.environ["HIVE_SEED"] = "777"
        try:
            assert HiveConfig.load(tmp_path).seed == 777
        finally:
            del os.environ["HIVE_SEED"]


class TestRunManifest:
    def test_manifest_written(self, tmp_path: Path) -> None:
        writer = LogWriter(tmp_path)
        run_id = writer.start_run(
            heartbeat=10,
            profiles=["coder"],
            agents=["coder-abc"],
            tools=["file_read"],
            seed=42,
            economy_enabled=True,
            model={"default_model": "claude-haiku-4-5", "temperature": 0.0},
        )
        manifest_path = tmp_path / "runs" / run_id / "manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert manifest["seed"] == 42
        assert manifest["economy_enabled"] is True
        assert manifest["model"]["default_model"] == "claude-haiku-4-5"
        assert manifest["run_id"] == run_id
        assert manifest["hive_version"]  # version string is captured
        assert manifest["agents"] == ["coder-abc"]
