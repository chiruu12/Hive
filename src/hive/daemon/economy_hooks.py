"""Economy side hooks for the daemon heartbeat (payday and life events)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from hive.agents.state import AgentState
from hive.config import get_config
from hive.daemon.agent_context import AgentContextCache
from hive.memory.events import EventType
from hive.runtime import Message
from hive.world.event_engine import EventEngine

if TYPE_CHECKING:
    from hive.daemon.loop import HiveDaemon

logger = logging.getLogger(__name__)


class EconomyHooks:
    """Payday ticks and stochastic life events outside the phase system."""

    def __init__(self, daemon: HiveDaemon, context: AgentContextCache) -> None:
        self._d = daemon
        self._ctx = context

    def process_payday(self, agents: list[AgentState]) -> None:
        for agent in agents:
            if self._d._ctx.world is None:
                continue
            job = self._d._ctx.world.agent_job(agent.agent_id)
            if job:
                self._d._ctx.world.work(agent.agent_id)

    async def process_life_events(self, agents: list[AgentState]) -> None:
        if not self._d._event_engine or not self._d._stats:
            return
        # Life events fire their own LLM calls outside the phase system, so honor
        # the daemon budget kill-switch here too.
        if self._d._budget_exceeded or self._d._budget.is_exceeded():
            return
        for agent in agents:
            if self._d._budget_exceeded or self._d._budget.is_exceeded():
                return
            self._d._stats.tick(agent.agent_id)
            events = self._d._event_engine.roll_events(agent.agent_id, self._d._cycle_count)

            for event in events:
                if self._d._budget_exceeded or self._d._budget.is_exceeded():
                    return
                prompt = self._d._event_engine.format_event_prompt(event)
                # Reuse the cached provider for this agent's model -- building a
                # fresh client per event (never closed) leaked connection pools.
                event_provider = self._ctx.get_provider(agent)
                profile = self._ctx.load_profile(agent.name)

                cfg = get_config().daemon
                reservation = await self._d._budget.reserve(
                    cfg.budget_reserve_usd_generation,
                    cfg.budget_reserve_tokens_generation,
                )
                if reservation is None:
                    return

                try:
                    result = await event_provider.generate_with_metadata(
                        messages=[
                            Message.system(
                                profile.build_system_prompt(
                                    economy_enabled=self._d._economy_enabled,
                                )
                            ),
                            Message.user(prompt),
                        ],
                        max_tokens=50,
                    )
                    await self._d._budget.commit(
                        reservation,
                        result.cost_usd or 0.0,
                        result.input_tokens + result.output_tokens,
                    )
                    self._d.persist_budget()
                    if self._d._budget_exceeded or self._d._budget.is_exceeded():
                        return
                    raw = result.message.content.strip() if result.message.content else ""
                    idx = EventEngine.parse_choice_index(raw, len(event.choices))
                    if idx is not None:
                        choice_id = event.choices[idx - 1].id
                    else:
                        logger.warning(
                            "Agent %s gave unparseable choice '%s' for event %s, defaulting",
                            agent.agent_id,
                            raw[:40],
                            event.name,
                        )
                        choice_id = event.choices[0].id
                except Exception as e:
                    await self._d._budget.release(reservation)
                    logger.warning(
                        "LLM error for event %s agent %s: %s",
                        event.name,
                        agent.agent_id,
                        e,
                    )
                    choice_id = event.choices[0].id

                outcome = self._d._event_engine.apply_choice(
                    agent.agent_id,
                    event,
                    choice_id,
                    self._d._cycle_count,
                )

                # D1: feed the chosen outcome back into the suffering system.
                suffering = self._ctx.get_suffering(agent.agent_id)
                if outcome.stressor_added:
                    chosen = next((c for c in event.choices if c.id == outcome.choice_id), None)
                    severity = chosen.stressor_severity if chosen else None
                    suffering.add_stressor(
                        outcome.stressor_added,
                        description=f"Triggered by life event: {event.name}",
                        observable_condition="Resolved by a positive life event or recovery",
                        initial_severity=severity,
                    )
                if outcome.stressor_resolved:
                    suffering.resolve(
                        outcome.stressor_resolved,
                        note=f"Relieved by life event: {event.name}",
                    )

                # D1: record the event in the agent's narrative (not just memory).
                self._d._identity.update_narrative(
                    agent.agent_id,
                    f"Life event: {event.name}",
                    outcome.choice_description,
                )

                session_id = f"sess-{agent.agent_id}"
                await self._ctx.emit(
                    agent.agent_id,
                    session_id,
                    EventType.EXISTENCE_CYCLE,
                    {
                        "life_event": event.name,
                        "choice": outcome.choice_description,
                        "stat_changes": outcome.stat_changes,
                        "follow_ups": outcome.follow_ups_triggered,
                        "stressor_added": outcome.stressor_added,
                        "stressor_resolved": outcome.stressor_resolved,
                    },
                )

                memory = self._ctx.get_memory(agent.agent_id)
                await memory.store(
                    f"Life event: {event.name}. Chose: {outcome.choice_description}",
                    metadata={"type": "life_event", "event_id": event.event_id},
                )
