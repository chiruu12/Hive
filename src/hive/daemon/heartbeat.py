"""Main daemon heartbeat loop — drives all agents each cycle."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from hive.agents.state import AgentStatus
from hive.config import get_config
from hive.daemon.agent_context import AgentContextCache
from hive.daemon.agent_cycle import AgentCycleRunner
from hive.daemon.economy_hooks import EconomyHooks
from hive.daemon.wakeup import CompositeWakeSource
from hive.logging.models import CycleLog

if TYPE_CHECKING:
    from hive.daemon.loop import HiveDaemon

logger = logging.getLogger(__name__)


class HeartbeatLoop:
    """Runs the daemon heartbeat until stopped or max_cycles reached."""

    def __init__(
        self,
        daemon: HiveDaemon,
        cycle_runner: AgentCycleRunner,
        economy: EconomyHooks,
        context: AgentContextCache,
    ) -> None:
        self._d = daemon
        self._cycle_runner = cycle_runner
        self._economy = economy
        self._ctx = context

    async def run(self, max_cycles: int | None = None) -> None:
        goals_completed = 0
        goals_abandoned = 0
        cycles_run = 0

        new_plugins = self._d._plugin_loader.discover()
        self._d._plugin_toolkits.extend(new_plugins)
        if new_plugins:
            logger.info("Loaded %d plugin toolkits", len(new_plugins))
            self._d._toolkit_factory.invalidate_tool_names_cache()

        while self._d._running:
            self._d.sync_pause_from_file()
            self._d.reload_config()
            self._d._cycle_count += 1
            cycles_run += 1

            if self._d._cycle_count % 10 == 0:
                new = self._d._plugin_loader.discover()
                self._d._plugin_toolkits.extend(new)
                if new:
                    logger.info("Hot-loaded %d new plugin toolkits", len(new))
                    self._d._toolkit_factory.invalidate_tool_names_cache()
            agents = await self._d._store.list_agents()
            alive = [a for a in agents if a.is_alive() and a.status != AgentStatus.PAUSED]
            crisis_count = sum(1 for a in alive if self._ctx.get_suffering(a.agent_id).in_crisis)

            # Hot-reloadable daemon settings (cycle_timeout, concurrency) are
            # refreshed each heartbeat via ``HiveDaemon.reload_config()``.
            cycle_timeout = get_config().daemon.cycle_timeout
            sem = asyncio.Semaphore(get_config().daemon.max_concurrent_agents)

            # Run agent cycles concurrently with bounded concurrency. Each cycle
            # is isolated (its own timeout + error handling), so one slow or
            # failing agent never blocks or breaks the others this heartbeat.
            results = await asyncio.gather(
                *(self._d._run_agent_cycle_guarded(agent, cycle_timeout, sem) for agent in alive)
            )
            goals_completed += sum(1 for r in results if r == "completed")
            goals_abandoned += sum(1 for r in results if r == "abandoned")

            killed = await self._d._sub_agents.auto_kill_expired()
            for kid in killed:
                logger.info("Auto-killed expired sub-agent: %s", kid)

            for agent in alive:
                if agent.spawned_by:
                    await self._d._store.increment_cycles(agent.agent_id)

            if self._d._economy_enabled:
                self._economy.process_payday(alive)
                await self._economy.process_life_events(alive)

            retention = get_config().retention
            if retention.enabled and self._d._cycle_count % retention.interval_cycles == 0:
                try:
                    counts = await self._d._store.cleanup(
                        days=retention.days,
                        session_ttl_hours=get_config().server.session_ttl_hours,
                    )
                    cleaned = {k: v for k, v in counts.items() if v}
                    if cleaned:
                        logger.info("Retention cleanup removed rows: %s", cleaned)
                except Exception:
                    logger.warning("Retention cleanup failed; will retry", exc_info=True)

            if self._d._cycle_count % 5 == 0 and alive:
                agent_ids = [a.agent_id for a in alive]
                report = await self._d._swarm.run_cycle(agent_ids)
                logger.info(
                    "Swarm learning cycle %d: success=%.0f%% patterns=%d recs=%d",
                    report.cycle_id,
                    report.swarm_success_rate * 100,
                    report.pattern_count,
                    len(report.recommendations),
                )
                # Act on recommendations via the swarm policy
                for rec in report.recommendations:
                    try:
                        await self._d._swarm_policy.handle_recommendation(
                            rec, self._d._specialization, agent_ids
                        )
                    except Exception:
                        logger.exception("Swarm policy failed for rec %s", rec.rec_id)

            self._d._log.log_cycle(
                CycleLog(
                    run_id=self._d._log.run_id,
                    cycle=self._d._cycle_count,
                    agents_active=len(alive),
                    agents_in_crisis=crisis_count,
                    goals_completed_this_cycle=goals_completed,
                    goals_abandoned_this_cycle=goals_abandoned,
                )
            )
            goals_completed = 0
            goals_abandoned = 0

            if max_cycles is not None and cycles_run >= max_cycles:
                break

            # Sleep the heartbeat, but wake on stop signal or external events
            # (A2A messages, nudges, file changes).  The CompositeWakeSource
            # races all sources and returns the first to fire, or "timeout"
            # when the heartbeat elapses.
            composite = CompositeWakeSource(self._d._wake_sources, self._d._heartbeat)
            if self._d._stop_event is not None:
                # Race: stop-event vs. external wake sources vs. heartbeat timeout
                stop_task = asyncio.create_task(self._d._stop_event.wait())
                wake_task = asyncio.create_task(composite.wait())
                try:
                    done, pending = await asyncio.wait(
                        [stop_task, wake_task],
                        timeout=self._d._heartbeat,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for t in pending:
                        t.cancel()
                        try:
                            await t
                        except asyncio.CancelledError:
                            pass
                except TimeoutError:
                    pass
            else:
                wake_reason = await composite.wait()
                if wake_reason != "timeout":
                    logger.info("Daemon woken by: %s", wake_reason)
