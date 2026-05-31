"""Tests for registry-driven world catalogs -- events and jobs (Phase 3 D2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hive.world.event_catalog import EVENTS
from hive.world.event_engine import EventEngine
from hive.world.events import LifeEvent
from hive.world.registry import EventRegistry, JobRegistry
from hive.world.state import AVAILABLE_JOBS, Job, WorldState
from hive.world.stats import StatsManager


@pytest.fixture(autouse=True)
def _reset_registries():
    EventRegistry._reset()
    JobRegistry._reset()
    yield
    EventRegistry._reset()
    JobRegistry._reset()


class TestEventRegistry:
    def test_default_seeded_with_builtin_events(self) -> None:
        reg = EventRegistry.default()
        assert len(reg.all()) == len(EVENTS)
        assert reg.get("rent_increase") is not None

    def test_register_and_get_custom_event(self) -> None:
        reg = EventRegistry()
        ev = LifeEvent(
            event_id="lottery",
            name="Lottery Win",
            description="You won!",
            category="financial",
            choices=[],
        )
        reg.register(ev)
        assert reg.get("lottery") is ev
        assert reg.get("missing") is None

    def test_register_replaces_by_id(self) -> None:
        reg = EventRegistry.default()
        before = len(reg.all())
        reg.register(
            LifeEvent(
                event_id="rent_increase",
                name="X",
                description="x",
                category="financial",
                choices=[],
            )
        )
        assert len(reg.all()) == before  # replaced, not appended

    def test_default_is_singleton(self) -> None:
        assert EventRegistry.default() is EventRegistry.default()


class TestJobRegistry:
    def test_default_seeded_with_builtin_jobs(self) -> None:
        reg = JobRegistry.default()
        assert len(reg.all()) == len(AVAILABLE_JOBS)
        assert reg.get("analyst") is not None

    def test_register_custom_job(self) -> None:
        reg = JobRegistry()
        reg.register(Job(job_id="pilot", title="Pilot", salary=200.0))
        assert reg.get("pilot").title == "Pilot"


class TestEngineUsesRegistry:
    def test_engine_fires_only_registered_events(self, tmp_path: Path) -> None:
        """An EventEngine with a custom registry sees only that registry's events."""
        reg = EventRegistry()
        reg.register(
            LifeEvent(
                event_id="only_one", name="Only", description="d", category="misc", choices=[]
            )
        )
        world = WorldState(tmp_path)
        engine = EventEngine(StatsManager(tmp_path), world, hive_dir=tmp_path, events=reg)
        assert engine._events.get("only_one") is not None
        assert engine._events.get("rent_increase") is None  # not in this registry

    def test_engine_defaults_to_builtin_registry(self, tmp_path: Path) -> None:
        world = WorldState(tmp_path)
        engine = EventEngine(StatsManager(tmp_path), world, hive_dir=tmp_path)
        assert engine._events.get("rent_increase") is not None


class TestWorldStateUsesJobRegistry:
    def test_registered_job_appears_in_new_world(self, tmp_path: Path) -> None:
        """A job registered before WorldState construction is picked up."""
        JobRegistry.default().register(Job(job_id="astronaut", title="Astronaut", salary=300.0))
        world = WorldState(tmp_path / "a")
        job_ids = {j.job_id for j in world._jobs}
        assert "astronaut" in job_ids
        assert "analyst" in job_ids  # built-ins still present
