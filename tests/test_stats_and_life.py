"""Tests for AgentStats, StatsManager, LifeSummary, and LifeDirectoryWriter."""

from __future__ import annotations

from pathlib import Path

import pytest

from hive.world.life_summary import CareerEntry, LifeDirectoryWriter, LifeMilestone, LifeSummary
from hive.world.stats import AgentStats, StatsManager

# ---------------------------------------------------------------------------
# AgentStats
# ---------------------------------------------------------------------------


class TestAgentStats:
    def test_defaults(self):
        s = AgentStats(agent_id="a1")
        assert s.happiness == 0.5
        assert s.health == 0.8
        assert s.reputation == 0.5
        assert s.energy == 1.0
        assert s.cycles_alive == 0

    def test_apply_absolute(self):
        s = AgentStats(agent_id="a1")
        result = s.apply("happiness", 0.2)
        assert result == 0.7
        assert s.happiness == 0.7

    def test_apply_percent(self):
        s = AgentStats(agent_id="a1", happiness=0.5)
        result = s.apply("happiness", 20, change_type="percent")
        assert result == pytest.approx(0.6)

    def test_apply_clamped_high(self):
        s = AgentStats(agent_id="a1", happiness=0.9)
        s.apply("happiness", 0.5)
        assert s.happiness == 1.0

    def test_apply_clamped_low(self):
        s = AgentStats(agent_id="a1", happiness=0.1)
        s.apply("happiness", -0.5)
        assert s.happiness == 0.0

    def test_apply_unknown_stat_returns_zero(self):
        s = AgentStats(agent_id="a1")
        result = s.apply("telepathy", 0.5)
        assert result == 0.0

    def test_tick_increments_cycles(self):
        s = AgentStats(agent_id="a1")
        s.tick()
        assert s.cycles_alive == 1
        s.tick()
        assert s.cycles_alive == 2

    def test_tick_recovers_energy(self):
        s = AgentStats(agent_id="a1", energy=0.5)
        s.tick()
        assert s.energy == 0.55

    def test_tick_energy_capped_at_1(self):
        s = AgentStats(agent_id="a1", energy=0.98)
        s.tick()
        assert s.energy == 1.0

    def test_summary_line(self):
        s = AgentStats(agent_id="a1", happiness=0.5, health=0.8, reputation=0.3, energy=1.0)
        line = s.summary_line()
        assert "HP:80%" in line
        assert "50%" in line
        assert "30%" in line
        assert "100%" in line


# ---------------------------------------------------------------------------
# StatsManager
# ---------------------------------------------------------------------------


class TestStatsManager:
    def test_get_creates_default(self, tmp_dir: Path):
        mgr = StatsManager(tmp_dir)
        s = mgr.get("new-agent")
        assert s.agent_id == "new-agent"
        assert s.happiness == 0.5

    def test_get_returns_same_instance(self, tmp_dir: Path):
        mgr = StatsManager(tmp_dir)
        s1 = mgr.get("a1")
        s2 = mgr.get("a1")
        assert s1 is s2

    def test_apply_effect_persists(self, tmp_dir: Path):
        mgr = StatsManager(tmp_dir)
        mgr.apply_effect("a1", "happiness", 0.1)

        mgr2 = StatsManager(tmp_dir)
        assert mgr2.get("a1").happiness == 0.6

    def test_apply_effect_money_passthrough(self, tmp_dir: Path):
        mgr = StatsManager(tmp_dir)
        result = mgr.apply_effect("a1", "money", 100.0)
        assert result == 100.0

    def test_apply_effect_percent(self, tmp_dir: Path):
        mgr = StatsManager(tmp_dir)
        mgr.get("a1").happiness = 0.5
        result = mgr.apply_effect("a1", "happiness", 20, change_type="percent")
        assert result == pytest.approx(0.6)

    def test_tick_persists(self, tmp_dir: Path):
        mgr = StatsManager(tmp_dir)
        mgr.get("a1").energy = 0.5
        mgr.tick("a1")

        mgr2 = StatsManager(tmp_dir)
        assert mgr2.get("a1").energy == 0.55
        assert mgr2.get("a1").cycles_alive == 1

    def test_get_all(self, tmp_dir: Path):
        mgr = StatsManager(tmp_dir)
        mgr.get("a1")
        mgr.get("a2")
        all_stats = mgr.get_all()
        assert "a1" in all_stats
        assert "a2" in all_stats
        assert len(all_stats) == 2

    def test_get_all_returns_copy(self, tmp_dir: Path):
        mgr = StatsManager(tmp_dir)
        mgr.get("a1")
        all_stats = mgr.get_all()
        all_stats["a3"] = AgentStats(agent_id="a3")
        assert "a3" not in mgr.get_all()

    def test_corrupt_file_handled(self, tmp_dir: Path):
        (tmp_dir / "agent_stats.json").write_text("not valid json")
        mgr = StatsManager(tmp_dir)
        # Should not raise
        s = mgr.get("a1")
        assert s.happiness == 0.5


# ---------------------------------------------------------------------------
# LifeSummary
# ---------------------------------------------------------------------------


class TestLifeSummary:
    def test_model_creation(self):
        summary = LifeSummary(
            agent_id="a1",
            display_name="Alice",
            role="detective",
            traits=["curious", "brave"],
            cycles_lived=100,
            final_money=500.0,
        )
        assert summary.agent_id == "a1"
        assert summary.display_name == "Alice"
        assert summary.cycles_lived == 100
        assert summary.traits == ["curious", "brave"]

    def test_defaults(self):
        summary = LifeSummary(agent_id="a1")
        assert summary.cycles_lived == 0
        assert summary.milestones == []
        assert summary.skills_learned == []
        assert summary.narrative == ""

    def test_career_entry(self):
        entry = CareerEntry(job_title="Detective", started_cycle=1, ended_cycle=50, salary=100.0)
        assert entry.job_title == "Detective"
        assert entry.ended_cycle == 50

    def test_milestone(self):
        m = LifeMilestone(
            cycle=10, description="Won a bet", category="gambling", stat_snapshot={"money": 50}
        )
        assert m.cycle == 10
        assert m.stat_snapshot == {"money": 50}


# ---------------------------------------------------------------------------
# LifeDirectoryWriter
# ---------------------------------------------------------------------------


class TestLifeDirectoryWriter:
    def test_write_and_read_roundtrip(self, tmp_dir: Path):
        writer = LifeDirectoryWriter(tmp_dir)
        summary = LifeSummary(
            agent_id="a1",
            display_name="Alice",
            role="detective",
            traits=["curious"],
            cycles_lived=50,
            final_stats={"happiness": 0.8, "health": 0.7},
            final_money=500.0,
            skills_learned=["investigation", "deduction"],
            milestones=[LifeMilestone(cycle=10, description="Solved case")],
        )

        writer.write(summary)
        loaded = writer.read("a1")

        assert loaded is not None
        assert loaded.agent_id == "a1"
        assert loaded.display_name == "Alice"
        assert loaded.cycles_lived == 50
        assert loaded.final_money == 500.0
        assert loaded.skills_learned == ["investigation", "deduction"]

    def test_read_nonexistent_returns_none(self, tmp_dir: Path):
        writer = LifeDirectoryWriter(tmp_dir)
        assert writer.read("nonexistent") is None

    def test_list_lives(self, tmp_dir: Path):
        writer = LifeDirectoryWriter(tmp_dir)

        for aid in ["a1", "a2", "a3"]:
            writer.write(LifeSummary(agent_id=aid))

        lives = writer.list_lives()
        assert set(lives) == {"a1", "a2", "a3"}

    def test_list_lives_empty(self, tmp_dir: Path):
        writer = LifeDirectoryWriter(tmp_dir)
        assert writer.list_lives() == []

    def test_read_biography(self, tmp_path: Path):
        writer = LifeDirectoryWriter(tmp_path)
        summary = LifeSummary(
            agent_id="a1",
            display_name="Alice",
            role="detective",
            traits=["curious", "brave"],
            cycles_lived=50,
            final_stats={"happiness": 0.8},
            final_money=500.0,
            skills_learned=["investigation"],
            milestones=[
                LifeMilestone(
                    cycle=10, description="Solved the case", stat_snapshot={"reputation": 0.2}
                )
            ],
            goals_completed=5,
            goals_abandoned=2,
            times_gambled=10,
            gambling_wins=4,
            gambling_losses=6,
            narrative="Alice lived a remarkable life.",
        )

        writer.write(summary)
        bio = writer.read_biography("a1")

        assert "# Life of Alice" in bio
        assert "detective" in bio
        assert "curious, brave" in bio
        assert "50 cycles" in bio
        assert "$500" in bio
        assert "80%" in bio
        assert "investigation" in bio
        assert "Solved the case" in bio
        assert "reputation: +0.2" in bio
        assert "Goals completed: 5" in bio
        assert "Times gambled: 10" in bio
        assert "won 4, lost 6" in bio
        assert "Alice lived a remarkable life." in bio

    def test_read_biography_nonexistent(self, tmp_dir: Path):
        writer = LifeDirectoryWriter(tmp_dir)
        assert writer.read_biography("nonexistent") == ""

    def test_write_atomic(self, tmp_path: Path):
        writer = LifeDirectoryWriter(tmp_path)
        summary = LifeSummary(agent_id="a1")
        writer.write(summary)

        # Should not leave .tmp files around
        agent_dir = tmp_path / "lives" / "a1"
        tmp_files = list(agent_dir.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_generate_basic(self, tmp_path: Path):
        """Test generate() with simple mocks."""
        from unittest.mock import MagicMock

        from hive.agents.identity import AgentIdentity
        from hive.world.events import EventOutcome

        writer = LifeDirectoryWriter(tmp_path)

        # Mock identity
        identity = AgentIdentity(
            agent_id="a1", display_name="Alice", traits=["brave"], domains=["investigation"]
        )
        identity_mgr = MagicMock()
        identity_mgr.load.return_value = identity

        # Mock stats
        from hive.world.stats import AgentStats

        stats = AgentStats(agent_id="a1", happiness=0.7, cycles_alive=25)
        stats_mgr = MagicMock()
        stats_mgr.get.return_value = stats

        # Mock world
        from pydantic import BaseModel

        class FakeFinances(BaseModel):
            balance: float = 100.0
            total_earned: float = 200.0
            total_spent: float = 100.0

        world = MagicMock()
        world.get_finances.return_value = FakeFinances()
        world.get_skills.return_value = []

        # Mock event engine
        event_engine = MagicMock()
        event_engine.get_history.return_value = [
            EventOutcome(
                agent_id="a1",
                event_id="gambling_bet",
                event_name="Casino Night",
                choice_id="bet_high",
                choice_description="Bet big",
                cycle=5,
                stat_changes={"money": -20},
            ),
        ]

        store = MagicMock()

        summary = writer.generate(
            "a1", identity_mgr, stats_mgr, world, event_engine, store, total_cycles=25
        )

        assert summary.agent_id == "a1"
        assert summary.display_name == "Alice"
        assert summary.role == "investigation"
        assert summary.traits == ["brave"]
        assert summary.cycles_lived == 25
        assert summary.final_money == 100.0
        assert summary.times_gambled == 1
        assert summary.gambling_losses == 1
        assert len(summary.milestones) == 1
