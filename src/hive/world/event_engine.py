"""Event engine — fires random life events and processes choices."""

import logging
import random

from hive.world.event_catalog import EVENT_MAP, EVENTS
from hive.world.events import EventOutcome, LifeEvent
from hive.world.state import WorldState
from hive.world.stats import AgentStats, StatsManager

logger = logging.getLogger(__name__)

EVENT_PROBABILITY = 0.3


class PendingFollowUp:
    def __init__(self, agent_id: str, event_id: str, fires_at_cycle: int):
        self.agent_id = agent_id
        self.event_id = event_id
        self.fires_at_cycle = fires_at_cycle


class EventEngine:
    """Fires random life events and tracks follow-ups."""

    def __init__(self, stats: StatsManager, world: WorldState):
        self._stats = stats
        self._world = world
        self._pending: list[PendingFollowUp] = []
        self._history: list[EventOutcome] = []

    def roll_events(self, agent_id: str, cycle: int) -> list[LifeEvent]:
        """Check for follow-ups + random event roll for this agent."""
        events_to_fire: list[LifeEvent] = []

        due = [p for p in self._pending if p.agent_id == agent_id and p.fires_at_cycle <= cycle]
        for p in due:
            ev = EVENT_MAP.get(p.event_id)
            if ev:
                events_to_fire.append(ev)
            self._pending.remove(p)

        if random.random() < EVENT_PROBABILITY:
            agent_stats = self._stats.get(agent_id)
            eligible = self._get_eligible(agent_stats)
            if eligible:
                events_to_fire.append(random.choice(eligible))

        return events_to_fire

    def apply_choice(
        self,
        agent_id: str,
        event: LifeEvent,
        choice_id: str,
        cycle: int,
    ) -> EventOutcome:
        """Apply a choice's effects and queue follow-ups."""
        choice = next((c for c in event.choices if c.id == choice_id), None)
        if not choice:
            choice = event.choices[0]

        stat_changes: dict[str, float] = {}
        for eff in choice.stat_effects:
            if eff.stat == "money":
                fin = self._world.get_finances(agent_id)
                fin.balance += eff.change
                if eff.change > 0:
                    fin.total_earned += eff.change
                else:
                    fin.total_spent += abs(eff.change)
                stat_changes["money"] = eff.change
            else:
                new_val = self._stats.apply_effect(
                    agent_id,
                    eff.stat,
                    eff.change,
                    eff.change_type,
                )
                stat_changes[eff.stat] = new_val

        follow_ups: list[str] = []
        for fu in choice.follow_up_events:
            if random.random() < fu.probability:
                self._pending.append(
                    PendingFollowUp(
                        agent_id=agent_id,
                        event_id=fu.event_id,
                        fires_at_cycle=cycle + fu.delay_cycles,
                    )
                )
                follow_ups.append(fu.event_id)

        outcome = EventOutcome(
            agent_id=agent_id,
            event_id=event.event_id,
            event_name=event.name,
            choice_id=choice.id,
            choice_description=choice.description,
            stat_changes=stat_changes,
            follow_ups_triggered=follow_ups,
            cycle=cycle,
        )
        self._history.append(outcome)
        return outcome

    def get_history(self, agent_id: str | None = None) -> list[EventOutcome]:
        if agent_id:
            return [o for o in self._history if o.agent_id == agent_id]
        return list(self._history)

    def _get_eligible(self, stats: AgentStats) -> list[LifeEvent]:
        eligible = []
        for ev in EVENTS:
            if ev.min_cycles_alive > stats.cycles_alive:
                continue
            if ev.event_id in {o.event_id for o in self._history[-20:]}:
                continue
            meets_prereqs = True
            for stat, threshold in ev.prerequisites.items():
                val = getattr(stats, stat, 0.5)
                if threshold > 0 and val < threshold:
                    meets_prereqs = False
                elif threshold < 0 and val > abs(threshold):
                    meets_prereqs = False
            if meets_prereqs:
                eligible.append(ev)
        return eligible

    def format_event_prompt(self, event: LifeEvent) -> str:
        """Format an event as a prompt for the LLM to choose."""
        lines = [f"LIFE EVENT: {event.name}", event.description, "", "Your choices:"]
        for c in event.choices:
            effects = []
            for e in c.stat_effects:
                sign = "+" if e.change > 0 else ""
                if e.change_type == "percent":
                    effects.append(f"{e.stat} {sign}{e.change}%")
                else:
                    effects.append(f"{e.stat} {sign}{e.change}")
            eff_str = f" ({', '.join(effects)})" if effects else ""
            lines.append(f'  {c.id}: "{c.description}"{eff_str}')
        lines.append("")
        lines.append(
            "Respond with ONLY the choice id (e.g. just the word like "
            f'"{event.choices[0].id}"). Nothing else.'
        )
        return "\n".join(lines)
