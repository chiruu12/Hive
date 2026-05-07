"""Tests for event engine, stats manager, and life summaries."""

from hive.world.event_catalog import EVENTS, EVENT_MAP
from hive.world.event_engine import EventEngine
from hive.world.events import Choice, LifeEvent, StatEffect
from hive.world.state import WorldState
from hive.world.stats import AgentStats, StatsManager


def test_stats_apply_valid(tmp_dir):
    mgr = StatsManager(tmp_dir)
    s = mgr.get("agent-1")
    assert s.happiness == 0.5
    mgr.apply_effect("agent-1", "happiness", 0.1)
    assert mgr.get("agent-1").happiness == 0.6


def test_stats_apply_unknown_warns(tmp_dir):
    mgr = StatsManager(tmp_dir)
    result = mgr.apply_effect("agent-1", "telepathy", 0.5)
    assert result == 0.0


def test_stats_clamped(tmp_dir):
    mgr = StatsManager(tmp_dir)
    mgr.apply_effect("agent-1", "happiness", 10.0)
    assert mgr.get("agent-1").happiness == 1.0
    mgr.apply_effect("agent-1", "happiness", -20.0)
    assert mgr.get("agent-1").happiness == 0.0


def test_stats_tick(tmp_dir):
    mgr = StatsManager(tmp_dir)
    s = mgr.get("agent-1")
    s.energy = 0.5
    mgr.tick("agent-1")
    assert mgr.get("agent-1").energy == 0.55
    assert mgr.get("agent-1").cycles_alive == 1


def test_stats_persist(tmp_dir):
    mgr1 = StatsManager(tmp_dir)
    mgr1.apply_effect("agent-1", "health", -0.2)

    mgr2 = StatsManager(tmp_dir)
    assert abs(mgr2.get("agent-1").health - 0.6) < 0.001


def test_event_engine_roll(tmp_dir):
    stats = StatsManager(tmp_dir)
    world = WorldState(tmp_dir)
    engine = EventEngine(stats, world, tmp_dir)

    stats.get("agent-1").cycles_alive = 20
    events = engine.roll_events("agent-1", cycle=1)
    # May or may not fire (30% chance), but shouldn't crash
    assert isinstance(events, list)


def test_event_engine_apply_choice(tmp_dir):
    stats = StatsManager(tmp_dir)
    world = WorldState(tmp_dir)
    engine = EventEngine(stats, world, tmp_dir)

    event = LifeEvent(
        event_id="test_event",
        name="Test Event",
        description="A test",
        category="test",
        choices=[
            Choice(
                id="opt_a",
                description="Option A",
                stat_effects=[
                    StatEffect(stat="money", change=-100),
                    StatEffect(stat="happiness", change=0.1),
                ],
            ),
        ],
    )

    outcome = engine.apply_choice("agent-1", event, "opt_a", cycle=5)
    assert outcome.choice_id == "opt_a"
    assert outcome.stat_changes["money"] == -100
    assert outcome.stat_changes["happiness"] == 0.1

    fin = world.get_finances("agent-1")
    assert fin.balance == 0.0  # 100 starting - 100

    assert stats.get("agent-1").happiness == 0.6  # 0.5 + 0.1


def test_event_engine_invalid_choice_defaults(tmp_dir):
    stats = StatsManager(tmp_dir)
    world = WorldState(tmp_dir)
    engine = EventEngine(stats, world, tmp_dir)

    event = LifeEvent(
        event_id="test",
        name="Test",
        description="Test",
        category="test",
        choices=[
            Choice(id="only_option", description="The only way", stat_effects=[]),
        ],
    )

    outcome = engine.apply_choice("agent-1", event, "nonexistent", cycle=1)
    assert outcome.choice_id == "only_option"


def test_event_engine_history_persists(tmp_dir):
    stats = StatsManager(tmp_dir)
    world = WorldState(tmp_dir)
    engine1 = EventEngine(stats, world, tmp_dir)

    event = LifeEvent(
        event_id="persist_test",
        name="Persist Test",
        description="Test",
        category="test",
        choices=[Choice(id="go", description="Go", stat_effects=[])],
    )
    engine1.apply_choice("agent-1", event, "go", cycle=1)
    assert len(engine1.get_history("agent-1")) == 1

    engine2 = EventEngine(stats, world, tmp_dir)
    assert len(engine2.get_history("agent-1")) == 1


def test_event_catalog_valid():
    for event in EVENTS:
        assert event.event_id
        assert event.name
        assert len(event.choices) >= 1
        for choice in event.choices:
            assert choice.id
            assert choice.description


def test_followup_delay_minimum():
    """All follow-ups should have delay_cycles >= 1."""
    for event in EVENTS:
        for choice in event.choices:
            for fu in choice.follow_up_events:
                assert fu.delay_cycles >= 1, (
                    f"Event {event.event_id} choice {choice.id} "
                    f"follow-up {fu.event_id} has delay_cycles={fu.delay_cycles}"
                )


def test_followup_events_exist():
    """All follow-up event_ids should reference existing events."""
    for event in EVENTS:
        for choice in event.choices:
            for fu in choice.follow_up_events:
                assert fu.event_id in EVENT_MAP, (
                    f"Event {event.event_id} references missing follow-up: {fu.event_id}"
                )
