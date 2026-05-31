"""Tests for the D1 simulation feedback loops.

Loop 1: world events -> stressors. Loop 2: stats -> goal generation.
Loop 3: outcomes/events -> narrative.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hive.agents.existence import ExistenceLoop
from hive.agents.profile import AgentProfile
from hive.agents.state import AgentState, AgentStatus
from hive.agents.suffering import SufferingState
from hive.config import HiveConfig, set_config
from hive.daemon.loop import HiveDaemon
from hive.models.base import BaseProvider
from hive.runtime.types import GenerateResult, Message
from hive.world.event_engine import EventEngine
from hive.world.events import Choice, LifeEvent
from hive.world.state import WorldState
from hive.world.stats import AgentStats, StatsManager


# --------------------------------------------------------------------------- #
# Loop 1 — events -> stressors
# --------------------------------------------------------------------------- #
class TestEventOutcomeCarriesStressor:
    def test_apply_choice_records_stressor_fields(self, tmp_path: Path) -> None:
        stats = StatsManager(tmp_path)
        world = WorldState(tmp_path)
        engine = EventEngine(stats, world, hive_dir=tmp_path)
        event = LifeEvent(
            event_id="loss",
            name="Big Loss",
            description="d",
            category="financial",
            choices=[
                Choice(
                    id="accept",
                    description="accept",
                    stressor="financial_strain",
                    stressor_severity=0.4,
                ),
            ],
        )
        outcome = engine.apply_choice("a1", event, "accept", cycle=1)
        assert outcome.stressor_added == "financial_strain"
        assert outcome.stressor_resolved is None


class _ChoiceProvider(BaseProvider):
    """Returns a fixed choice index for life-event prompts."""

    def __init__(self, index: str = "1") -> None:
        super().__init__("choice")
        self._index = index

    @property
    def available(self) -> bool:
        return True

    async def generate_with_metadata(self, *a: Any, **k: Any) -> GenerateResult:
        return GenerateResult(message=Message.assistant(self._index), model="choice")

    async def generate_structured(self, *a: Any, **k: Any) -> Any:  # pragma: no cover
        raise NotImplementedError


@pytest.fixture(autouse=True)
def _economy_on():
    cfg = HiveConfig()
    cfg.economy.enabled = True
    set_config(cfg)
    yield


class TestDaemonWiresEventToStressorAndNarrative:
    @pytest.mark.asyncio
    async def test_event_adds_stressor_and_records_narrative(self, tmp_path, monkeypatch) -> None:
        daemon = HiveDaemon(tmp_path / ".hive", heartbeat=0, logs_dir=tmp_path / "logs")
        assert daemon._event_engine is not None  # economy enabled -> engine exists
        await daemon._store.initialize()
        agent = AgentState(agent_id="a1", name="ada", role="t", model="m", status=AgentStatus.IDLE)
        await daemon._store.save_agent(agent)
        # Identity must exist for update_narrative to persist.
        daemon._identity.load_or_create("a1", AgentProfile(name="ada", role="t"))

        event = LifeEvent(
            event_id="loss",
            name="Big Loss",
            description="You lost big.",
            category="financial",
            choices=[
                Choice(
                    id="accept",
                    description="Accept it",
                    stressor="financial_strain",
                    stressor_severity=0.5,
                ),
            ],
        )
        monkeypatch.setattr(daemon._event_engine, "roll_events", lambda aid, c: [event])
        monkeypatch.setattr(
            "hive.daemon.loop.create_runtime_provider", lambda m: _ChoiceProvider("1")
        )

        await daemon._process_life_events([agent])

        suffering = daemon._get_suffering("a1")
        assert any(s.type == "financial_strain" for s in suffering.active)
        identity = daemon._identity.load("a1")
        assert identity is not None and "Big Loss" in identity.narrative

    @pytest.mark.asyncio
    async def test_event_resolves_stressor(self, tmp_path, monkeypatch) -> None:
        daemon = HiveDaemon(tmp_path / ".hive", heartbeat=0, logs_dir=tmp_path / "logs")
        await daemon._store.initialize()
        agent = AgentState(agent_id="a1", name="ada", role="t", model="m", status=AgentStatus.IDLE)
        await daemon._store.save_agent(agent)
        daemon._identity.load_or_create("a1", AgentProfile(name="ada", role="t"))
        # Pre-seed the stressor that the event will relieve.
        daemon._get_suffering("a1").add_stressor("financial_strain", "test", "cond", 0.5)

        event = LifeEvent(
            event_id="win",
            name="Windfall",
            description="Found money.",
            category="financial",
            choices=[
                Choice(id="save", description="Save it", resolves_stressor="financial_strain")
            ],
        )
        monkeypatch.setattr(daemon._event_engine, "roll_events", lambda aid, c: [event])
        monkeypatch.setattr(
            "hive.daemon.loop.create_runtime_provider", lambda m: _ChoiceProvider("1")
        )

        await daemon._process_life_events([agent])
        suffering = daemon._get_suffering("a1")
        assert not any(s.type == "financial_strain" for s in suffering.active)
        assert any(s.type == "financial_strain" for s in suffering.history)


# --------------------------------------------------------------------------- #
# Loop 2 — stats -> goal generation
# --------------------------------------------------------------------------- #
class TestStatsInGoalPrompt:
    def _loop(self, stats: AgentStats | None) -> ExistenceLoop:
        return ExistenceLoop(
            agent_id="a1",
            profile=AgentProfile(name="ada", role="tester"),
            provider=None,
            store=None,  # type: ignore[arg-type]
            event_log=None,  # type: ignore[arg-type]
            hive_dir=None,
            stats=stats,
        )

    def test_condition_section_present_with_stats(self) -> None:
        loop = self._loop(AgentStats(agent_id="a1", health=0.3, energy=0.2, happiness=0.4))
        prompt = loop._build_prompt(SufferingState(agent_id="a1"), [], [], "", [])
        assert "current condition" in prompt.lower()
        assert "Health: 30%" in prompt
        assert "Energy: 20%" in prompt

    def test_condition_section_absent_without_stats(self) -> None:
        loop = self._loop(None)
        prompt = loop._build_prompt(SufferingState(agent_id="a1"), [], [], "", [])
        assert "current condition" not in prompt.lower()
