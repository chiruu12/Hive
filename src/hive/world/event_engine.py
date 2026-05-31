"""Event engine — fires random life events and processes choices."""

import logging
import random
from pathlib import Path

from hive.world.events import EventOutcome, LifeEvent
from hive.world.registry import EventRegistry
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

    def __init__(
        self,
        stats: StatsManager,
        world: WorldState,
        hive_dir: Path | None = None,
        events: EventRegistry | None = None,
    ):
        self._stats = stats
        self._world = world
        self._events = events or EventRegistry.default()
        self._pending: list[PendingFollowUp] = []
        self._history: list[EventOutcome] = []
        self._history_path = (hive_dir / "event_history.jsonl") if hive_dir else None
        self._load_history()

    def _load_history(self) -> None:
        if not self._history_path or not self._history_path.exists():
            return
        for line in self._history_path.read_text().strip().splitlines():
            if line.strip():
                try:
                    self._history.append(EventOutcome.model_validate_json(line))
                except Exception:
                    pass

    def _persist_outcome(self, outcome: EventOutcome) -> None:
        if not self._history_path:
            return
        with open(self._history_path, "a") as f:
            f.write(outcome.model_dump_json() + "\n")

    def roll_events(self, agent_id: str, cycle: int) -> list[LifeEvent]:
        """Check for follow-ups + random event roll for this agent."""
        events_to_fire: list[LifeEvent] = []

        due = [p for p in self._pending if p.agent_id == agent_id and p.fires_at_cycle <= cycle]
        for p in due:
            ev = self._events.get(p.event_id)
            if ev:
                events_to_fire.append(ev)
            self._pending.remove(p)

        if random.random() < EVENT_PROBABILITY:
            agent_stats = self._stats.get(agent_id)
            eligible = self._get_eligible(agent_id, agent_stats)
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
        """Apply a choice's effects with luck and chaos, then queue follow-ups."""
        choice = next((c for c in event.choices if c.id == choice_id), None)
        if not choice:
            choice = event.choices[0]

        luck = random.gauss(1.0, 0.25)
        luck = max(0.3, min(2.0, luck))

        stat_changes: dict[str, float] = {}
        for eff in choice.stat_effects:
            actual = eff.change * luck
            if eff.stat == "money":
                actual = round(actual)
                self._world.adjust_balance(agent_id, actual)
                stat_changes["money"] = actual
            else:
                self._stats.apply_effect(
                    agent_id,
                    eff.stat,
                    actual,
                    eff.change_type,
                )
                stat_changes[eff.stat] = round(actual, 3)

        follow_ups: list[str] = []
        for fu in choice.follow_up_events:
            if random.random() < fu.probability:
                delay = max(fu.delay_cycles, 1)
                self._pending.append(
                    PendingFollowUp(
                        agent_id=agent_id,
                        event_id=fu.event_id,
                        fires_at_cycle=cycle + delay,
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
        self._persist_outcome(outcome)
        return outcome

    def get_history(self, agent_id: str | None = None) -> list[EventOutcome]:
        if agent_id:
            return [o for o in self._history if o.agent_id == agent_id]
        return list(self._history)

    def _get_eligible(self, agent_id: str, stats: AgentStats) -> list[LifeEvent]:
        eligible = []
        agent_recent: set[str] = set()
        count = 0
        for outcome in reversed(self._history):
            if count >= 20:
                break
            if outcome.agent_id == agent_id:
                agent_recent.add(outcome.event_id)
                count += 1
        for ev in self._events.all():
            if ev.min_cycles_alive > stats.cycles_alive:
                continue
            if ev.event_id in agent_recent:
                continue
            meets_prereqs = True
            for stat, threshold in ev.prerequisites.items():
                val = getattr(stats, stat, None)
                if val is None:
                    meets_prereqs = False
                    break
                if threshold > 0 and val < threshold:
                    meets_prereqs = False
                elif threshold < 0 and val > abs(threshold):
                    meets_prereqs = False
            if meets_prereqs:
                eligible.append(ev)
        return eligible

    def format_event_prompt(self, event: LifeEvent) -> str:
        """Format an event as a prompt for the LLM to choose.

        Uses numeric indices (1, 2, 3) so small models can respond with
        just a number instead of remembering string IDs.
        """
        lines = [f"LIFE EVENT: {event.name}", event.description, "", "Your choices:"]
        for i, c in enumerate(event.choices, 1):
            effects = []
            for e in c.stat_effects:
                sign = "+" if e.change > 0 else ""
                if e.change_type == "percent":
                    effects.append(f"{e.stat} {sign}{e.change}%")
                else:
                    effects.append(f"{e.stat} {sign}{e.change}")
            eff_str = f" ({', '.join(effects)})" if effects else ""
            lines.append(f'  {i}. "{c.description}"{eff_str}')
        lines.append("")
        lines.append(
            f"Respond with ONLY the number of your choice (1-{len(event.choices)}). Nothing else."
        )
        return "\n".join(lines)

    @staticmethod
    def parse_choice_index(raw_response: str, num_choices: int) -> int | None:
        """Extract a 1-based choice index from model response."""
        import re

        text = raw_response.strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        for match in re.finditer(r"\b(\d+)\b", text):
            idx = int(match.group(1))
            if 1 <= idx <= num_choices:
                return idx
        return None
