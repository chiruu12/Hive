"""Phase guards — veto entry into a daemon cycle phase.

A :class:`PhaseGuard` is registered on the :class:`~hive.daemon.hooks.HookRegistry`
for a specific :class:`~hive.daemon.phase.CyclePhase`.  Before the daemon enters
that phase it calls ``should_proceed`` on every registered guard; if *any* guard
returns ``False`` the phase is skipped and the cycle returns ``"guarded"``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from hive.daemon.phase import PhaseGate

if TYPE_CHECKING:
    from hive.daemon.budget import BudgetTracker

logger = logging.getLogger(__name__)


@runtime_checkable
class PhaseGuard(Protocol):
    """Protocol for phase guards."""

    async def should_proceed(self, gate: PhaseGate) -> bool:
        """Return ``True`` to allow the phase, ``False`` to skip it."""
        ...


class CostBudgetGuard:
    """Blocks phases when the daemon-level budget is exceeded.

    Requires a :class:`~hive.daemon.budget.BudgetTracker` instance.  The daemon
    always passes its tracker in production.  If no tracker is provided (tests
    only), the guard blocks LLM phases fail-closed after logging once.
    """

    def __init__(self, budget: BudgetTracker | None = None) -> None:
        self._budget = budget
        self._warned_missing_budget = False

    async def should_proceed(self, gate: PhaseGate) -> bool:
        if self._budget is None:
            if not self._warned_missing_budget:
                logger.warning(
                    "CostBudgetGuard has no BudgetTracker — blocking %s (fail-closed)",
                    gate.phase.value,
                )
                self._warned_missing_budget = True
            return False
        if self._budget.is_exceeded() or self._budget.is_at_capacity():
            logger.warning(
                "Budget exceeded or at capacity — blocking %s for %s",
                gate.phase.value,
                gate.agent_id,
            )
            return False
        return True


class ManualPauseGuard:
    """Blocks all phases when ``paused`` is set to ``True``.

    Allows operators to freeze the daemon via the API or CLI without
    stopping the process.
    """

    def __init__(self) -> None:
        self.paused: bool = False

    async def should_proceed(self, gate: PhaseGate) -> bool:
        if self.paused:
            logger.info("Daemon paused — blocking %s", gate.phase.value)
            return False
        return True
