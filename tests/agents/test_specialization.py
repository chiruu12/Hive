"""Tests for SpecializationTracker."""

from __future__ import annotations

from hive.agents.specialization import MAX_HISTORY_PER_AGENT, SpecializationTracker


def test_records_build_a_profile() -> None:
    tracker = SpecializationTracker()
    for _ in range(5):
        tracker.record("a1", "coding", success=True)
    tracker.record("a1", "coding", success=False)
    profile = tracker.get_profile("a1")
    assert profile.total_tasks == 6
    assert tracker.route_score("a1", "coding") > 0.5


def test_history_is_capped_per_agent() -> None:
    # The tracker is a daemon-lifetime singleton; per-agent history must stay
    # bounded so it can't leak memory (or make _recompute scan an ever-growing
    # list) over a long run.
    tracker = SpecializationTracker()
    for _ in range(MAX_HISTORY_PER_AGENT + 50):
        tracker.record("a1", "coding", success=True)
    assert len(tracker._history["a1"]) == MAX_HISTORY_PER_AGENT
    # A second agent is tracked independently (not evicted by the first).
    tracker.record("a2", "research", success=True)
    assert len(tracker._history["a2"]) == 1
