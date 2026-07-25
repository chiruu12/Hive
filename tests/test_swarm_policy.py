"""Tests for SwarmPolicy protocol and implementations."""

from __future__ import annotations

import logging

import pytest

from hive.agents.swarm import LearningReport, Recommendation
from hive.agents.swarm_policy import DefaultSwarmPolicy, PassiveSwarmPolicy


def _make_rec(category: str = "routing", target: str = "agent-1") -> Recommendation:
    return Recommendation(
        rec_id="rec-test-1",
        category=category,
        priority=5,
        description=f"Test {category} recommendation",
        target_agent=target,
        cycle_id=1,
    )


class _FakeTracker:
    """Minimal specialization tracker stub."""

    def best_agent_for(self, task_type: str, agents: list[str]) -> str:
        return agents[0] if agents else ""

    def get_all_profiles(self) -> dict:
        return {}


class TestDefaultSwarmPolicy:
    @pytest.mark.asyncio
    async def test_routing_logs_info(self, caplog):
        policy = DefaultSwarmPolicy()
        rec = _make_rec("routing")
        with caplog.at_level(logging.INFO):
            await policy.handle_recommendation(rec, _FakeTracker(), ["a1", "a2"])
        assert any("Swarm routing" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_knowledge_logs_warning(self, caplog):
        policy = DefaultSwarmPolicy()
        rec = _make_rec("knowledge")
        with caplog.at_level(logging.WARNING):
            await policy.handle_recommendation(rec, _FakeTracker(), ["a1"])
        assert any("Swarm knowledge alert" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_specialization_logs_info(self, caplog):
        policy = DefaultSwarmPolicy()
        rec = _make_rec("specialization")
        with caplog.at_level(logging.INFO):
            await policy.handle_recommendation(rec, _FakeTracker(), ["a1"])
        assert any("Swarm specialization" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_unknown_category_logs_debug(self, caplog):
        policy = DefaultSwarmPolicy()
        rec = _make_rec("unknown_category")
        with caplog.at_level(logging.DEBUG):
            await policy.handle_recommendation(rec, _FakeTracker(), ["a1"])
        assert any("Unknown recommendation category" in r.message for r in caplog.records)


class TestPassiveSwarmPolicy:
    @pytest.mark.asyncio
    async def test_passive_does_nothing(self, caplog):
        policy = PassiveSwarmPolicy()
        rec = _make_rec("routing")
        with caplog.at_level(logging.DEBUG):
            await policy.handle_recommendation(rec, _FakeTracker(), ["a1"])
        assert any("passive" in r.message for r in caplog.records)


class TestLearningReportSummary:
    def test_to_summary_basic(self):
        report = LearningReport(
            cycle_id=5,
            agent_count=3,
            swarm_success_rate=0.75,
            total_goals=20,
            total_completed=15,
            total_abandoned=5,
            pattern_count=2,
            specialization_avg=0.45,
        )
        text = report.to_summary()
        assert "Cycle 5" in text
        assert "3 agents" in text
        assert "75%" in text
        assert "patterns=2" in text

    def test_to_summary_with_recommendations(self):
        report = LearningReport(
            cycle_id=1,
            recommendations=[_make_rec("routing")],
        )
        text = report.to_summary()
        assert "Recommendations (1)" in text
        assert "routing" in text


class TestHiveDaemonSwarmDefault:
    def test_default_policy_is_passive(self, tmp_path):
        from hive.config import HiveConfig, set_config
        from hive.daemon.loop import HiveDaemon

        hive = tmp_path / ".hive"
        hive.mkdir()
        (hive / "sessions").mkdir()
        (hive / "workspaces").mkdir()
        (hive / "comms").mkdir()
        (hive / "agent_memory").mkdir()
        cfg = HiveConfig()
        cfg.economy.enabled = False
        set_config(cfg)
        cfg.save(hive)

        daemon = HiveDaemon(hive, heartbeat=60, logs_dir=tmp_path / "logs")
        assert isinstance(daemon._swarm_policy, PassiveSwarmPolicy)

    def test_to_summary_with_deltas(self):
        report = LearningReport(
            cycle_id=1,
            deltas={"success_rate_delta": 0.1, "goal_delta": -2.0},
        )
        text = report.to_summary()
        assert "success_rate_delta" in text
        assert "+0.10" in text
