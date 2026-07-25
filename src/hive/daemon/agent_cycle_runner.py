"""Agent cycle runner shell — guarded execution and hook orchestration."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from hive.agents.state import AgentState, AgentStatus
from hive.config import get_config
from hive.daemon.agent_context import AgentContextCache
from hive.daemon.agent_cycle_phases import run_inner
from hive.daemon.budget import BudgetReservation
from hive.daemon.phase import CyclePhase, PhaseGate

if TYPE_CHECKING:
    from hive.daemon.loop import HiveDaemon

logger = logging.getLogger(__name__)


class AgentCycleRunner:
    """Runs one agent's six-phase heartbeat cycle."""

    def __init__(self, daemon: HiveDaemon, context: AgentContextCache) -> None:
        self._d = daemon
        self._ctx = context

    async def run_guarded(
        self, agent: AgentState, cycle_timeout: int, sem: asyncio.Semaphore
    ) -> str | None:
        """Run one agent's cycle under the concurrency limit, isolating failures."""
        async with sem:
            try:
                if cycle_timeout > 0:
                    timed: str | None = await asyncio.wait_for(
                        self._d._run_agent_cycle(agent), timeout=cycle_timeout
                    )
                    return timed
                cycle_result: str = await self._d._run_agent_cycle(agent)
                return cycle_result
            except TimeoutError:
                preserve = get_config().daemon.preserve_active_goals_on_timeout
                logger.warning(
                    "Cycle %d: agent %s timed out after %ds, %s",
                    self._d._cycle_count,
                    agent.agent_id,
                    cycle_timeout,
                    "parking goal" if preserve else "abandoning goal",
                )
                try:
                    active_goal = await self._d._store.get_active_goal(agent.agent_id)
                    if active_goal and not preserve:
                        await self._d._store.abandon_goal(active_goal["goal_id"])
                    await self._d._store.update_agent_status(agent.agent_id, AgentStatus.IDLE)
                except Exception:
                    logger.error(
                        "Cycle %d: could not reset agent %s after timeout",
                        self._d._cycle_count,
                        agent.agent_id,
                        exc_info=True,
                    )
                return None
            except Exception as e:
                logger.error(
                    "Cycle %d failed for agent %s: %s",
                    self._d._cycle_count,
                    agent.agent_id,
                    e,
                    exc_info=True,
                )
                try:
                    await self._d._store.update_agent_status(
                        agent.agent_id, AgentStatus.ERROR, error=str(e)
                    )
                except Exception:
                    logger.error(
                        "Cycle %d: could not mark agent %s as ERROR",
                        self._d._cycle_count,
                        agent.agent_id,
                        exc_info=True,
                    )
                return None

    async def run(self, agent: AgentState) -> str:
        await self._d._hooks.emit(
            "cycle_start", agent_id=agent.agent_id, cycle_num=self._d._cycle_count
        )

        suffering = self._ctx.get_suffering(agent.agent_id)
        result = "idle"
        try:
            result = await run_inner(self, agent, suffering)
        except Exception:
            result = "error"
            raise
        finally:
            await self._d._hooks.emit(
                "suffering_changed",
                agent_id=agent.agent_id,
                suffering_state=suffering,
            )
            await self._d._hooks.emit(
                "cycle_end",
                agent_id=agent.agent_id,
                cycle_num=self._d._cycle_count,
                result=result,
            )
        return result

    async def _enter_phase(self, phase: CyclePhase, agent_id: str) -> bool:
        """Check guards and emit phase_enter hook.  Returns ``True`` if allowed."""
        gate = PhaseGate(phase=phase, agent_id=agent_id, cycle_num=self._d._cycle_count)
        allowed = await self._d._hooks.check_guards(gate)
        if allowed:
            await self._d._hooks.emit(
                "phase_enter",
                phase=phase,
                agent_id=agent_id,
                cycle_num=self._d._cycle_count,
            )
        return bool(allowed)

    async def _exit_phase(self, phase: CyclePhase, agent_id: str) -> None:
        """Emit phase_exit hook."""
        await self._d._hooks.emit(
            "phase_exit",
            phase=phase,
            agent_id=agent_id,
            cycle_num=self._d._cycle_count,
        )

    async def _commit_budget(
        self,
        reservation: BudgetReservation | None,
        cost_usd: float,
        tokens: int,
    ) -> None:
        await self._d._budget.commit(reservation, cost_usd, tokens)
        self._d.persist_budget()

    def _reserve_estimates(self, phase: CyclePhase) -> tuple[float, int]:
        cfg = get_config().daemon
        if phase == CyclePhase.GOAL_PURSUIT:
            return cfg.budget_reserve_usd_pursuit, cfg.budget_reserve_tokens_pursuit
        return cfg.budget_reserve_usd_generation, cfg.budget_reserve_tokens_generation
