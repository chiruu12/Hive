"""Registries for world content -- life events and jobs (Phase 3 D2).

Mirror ``StressorRegistry`` / ``PatternRegistry``: a default singleton seeded
from the built-in catalogs, plus ``register()`` / ``get()`` / ``all()`` so
applications can add content without editing the catalog modules, and pass a
custom registry per ``EventEngine`` / ``WorldState`` for isolated content sets.
"""

from __future__ import annotations

from typing import ClassVar

from hive.world.event_catalog import EVENTS
from hive.world.events import LifeEvent
from hive.world.state import AVAILABLE_JOBS, Job


class EventRegistry:
    """Extensible registry of life events. ``default()`` is seeded with EVENTS."""

    _instance: ClassVar[EventRegistry | None] = None

    def __init__(self) -> None:
        self._events: dict[str, LifeEvent] = {}

    def register(self, event: LifeEvent) -> None:
        """Add or replace an event by its event_id."""
        self._events[event.event_id] = event

    def get(self, event_id: str) -> LifeEvent | None:
        """Return the event with this id, or None."""
        return self._events.get(event_id)

    def all(self) -> list[LifeEvent]:
        """Return all registered events."""
        return list(self._events.values())

    @classmethod
    def default(cls) -> EventRegistry:
        if cls._instance is None:
            cls._instance = cls()
            for event in EVENTS:
                cls._instance.register(event)
        return cls._instance

    @classmethod
    def _reset(cls) -> None:
        cls._instance = None


class JobRegistry:
    """Extensible registry of jobs. ``default()`` is seeded with AVAILABLE_JOBS."""

    _instance: ClassVar[JobRegistry | None] = None

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def register(self, job: Job) -> None:
        """Add or replace a job by its job_id."""
        self._jobs[job.job_id] = job

    def get(self, job_id: str) -> Job | None:
        """Return the job with this id, or None."""
        return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        """Return all registered jobs."""
        return list(self._jobs.values())

    @classmethod
    def default(cls) -> JobRegistry:
        if cls._instance is None:
            cls._instance = cls()
            for job in AVAILABLE_JOBS:
                cls._instance.register(job)
        return cls._instance

    @classmethod
    def _reset(cls) -> None:
        cls._instance = None
