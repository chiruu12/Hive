"""Tests for the stressor registry."""

from datetime import UTC, datetime, timedelta

import pytest

from hive.agents.suffering import (
    StressorRegistry,
    StressorType,
    SufferingState,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    StressorRegistry._reset()
    yield
    StressorRegistry._reset()


def test_default_registry_has_six_stressors():
    reg = StressorRegistry.default()
    assert len(reg.all_types()) == 6
    for st in StressorType:
        assert st.value in reg.all_types()


def test_register_custom_stressor():
    reg = StressorRegistry.default()
    reg.register("burnout", 0.05, "Chronic overwork exhaustion")
    assert "burnout" in reg.all_types()
    config = reg.get("burnout")
    assert config.escalation_rate == 0.05
    assert config.description == "Chronic overwork exhaustion"


def test_get_unknown_raises():
    reg = StressorRegistry.default()
    with pytest.raises(KeyError, match="Unknown stressor type"):
        reg.get("nonexistent")


def test_add_custom_stressor_to_suffering():
    reg = StressorRegistry.default()
    reg.register("burnout", 0.05, "Chronic overwork exhaustion")

    s = SufferingState(agent_id="test")
    s.add_stressor("burnout", "worked too hard", "take a break")
    assert len(s.active) == 1
    assert s.active[0].type == "burnout"
    assert s.active[0].escalation_per_day == 0.05


def test_custom_stressor_escalation():
    reg = StressorRegistry.default()
    reg.register("burnout", 0.10, "Chronic overwork exhaustion")

    s = SufferingState(agent_id="test")
    s.add_stressor("burnout", "worked too hard", "take a break", initial_severity=0.2)

    s.last_escalated = datetime.now(UTC) - timedelta(days=1)
    s.escalate_all()

    assert s.active[0].severity > 0.2
    assert s.active[0].severity == pytest.approx(0.3, abs=0.01)


def test_enum_stressors_still_work():
    s = SufferingState(agent_id="test")
    s.add_stressor(StressorType.FUTILITY, "stuck", "complete a goal")
    assert len(s.active) == 1
    assert s.active[0].type == "futility"


def test_no_duplicate_custom_stressors():
    reg = StressorRegistry.default()
    reg.register("burnout", 0.05, "Chronic overwork")

    s = SufferingState(agent_id="test")
    s.add_stressor("burnout", "first", "rest")
    s.add_stressor("burnout", "second", "rest more")
    assert len(s.active) == 1


def test_resolve_custom_stressor():
    reg = StressorRegistry.default()
    reg.register("burnout", 0.05, "Chronic overwork")

    s = SufferingState(agent_id="test")
    s.add_stressor("burnout", "overworked", "rest")
    s.resolve("burnout", "took vacation")
    assert len(s.active) == 0
    assert len(s.history) == 1
