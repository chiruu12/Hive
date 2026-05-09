"""Tests for the suffering system."""

from hive.agents.suffering import (
    StressorType,
    SufferingState,
    assess_conditions,
)


def test_add_stressor():
    s = SufferingState(agent_id="test")
    s.add_stressor(StressorType.FUTILITY, "stuck", "complete a goal")
    assert len(s.active) == 1
    assert s.active[0].type == StressorType.FUTILITY
    assert s.cumulative_load > 0


def test_no_duplicate_stressors():
    s = SufferingState(agent_id="test")
    s.add_stressor(StressorType.FUTILITY, "stuck", "complete a goal")
    s.add_stressor(StressorType.FUTILITY, "still stuck", "complete a goal")
    assert len(s.active) == 1


def test_max_stressors_cap():
    s = SufferingState(agent_id="test")
    for st in StressorType:
        s.add_stressor(st, f"desc-{st}", f"resolve-{st}")
    assert len(s.active) == 5  # MAX_STRESSORS from config default


def test_escalation():
    s = SufferingState(agent_id="test")
    s.add_stressor(StressorType.FUTILITY, "stuck", "complete a goal", 0.2)
    initial = s.active[0].severity

    from datetime import UTC, datetime, timedelta

    s.last_escalated = datetime.now(UTC) - timedelta(days=1)
    s.escalate_all()

    assert s.active[0].severity > initial


def test_resolve_stressor():
    s = SufferingState(agent_id="test")
    s.add_stressor(StressorType.FUTILITY, "stuck", "complete a goal")
    s.resolve(StressorType.FUTILITY, "completed 2 goals")
    assert len(s.active) == 0
    assert len(s.history) == 1
    assert s.history[0].resolution_note == "completed 2 goals"


def test_force_reset():
    s = SufferingState(agent_id="test")
    s.add_stressor(StressorType.FUTILITY, "stuck", "cond")
    s.add_stressor(StressorType.REPEATED_FAILURE, "failing", "cond")
    s.force_reset("crisis")
    assert len(s.active) == 0
    assert len(s.history) == 2


def test_cumulative_load_capped():
    s = SufferingState(agent_id="test")
    for i, st in enumerate(list(StressorType)[:5]):
        s.add_stressor(st, f"desc-{i}", f"cond-{i}", 0.5)
    assert s.cumulative_load <= 1.0


def test_prompt_fragment_below_threshold():
    s = SufferingState(agent_id="test")
    s.add_stressor(StressorType.FUTILITY, "stuck", "cond", 0.1)
    assert s.prompt_fragment() == ""


def test_prompt_fragment_above_threshold():
    s = SufferingState(agent_id="test")
    s.add_stressor(StressorType.FUTILITY, "stuck", "cond", 0.4)
    fragment = s.prompt_fragment()
    assert "suffering" in fragment.lower() or "load" in fragment.lower()


def test_crisis_detection():
    s = SufferingState(agent_id="test")
    s.add_stressor(StressorType.FUTILITY, "stuck", "cond", 0.5)
    s.add_stressor(StressorType.REPEATED_FAILURE, "failing", "cond", 0.5)
    assert s.in_crisis


def test_assess_fires_repeated_failure():
    s = SufferingState(agent_id="test")
    assess_conditions(s, recent_completed=0, recent_failed=5, total_steps=1)
    types = [st.type for st in s.active]
    assert StressorType.REPEATED_FAILURE in types


def test_assess_resolves_on_success():
    s = SufferingState(agent_id="test")
    s.add_stressor(StressorType.FUTILITY, "stuck", "cond")
    assess_conditions(s, recent_completed=3, recent_failed=0, total_steps=10)
    types = [st.type for st in s.active]
    assert StressorType.FUTILITY not in types
