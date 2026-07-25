"""Daemon hook system — register callbacks for lifecycle events."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hive.daemon.phase import CyclePhase, PhaseGate

logger = logging.getLogger(__name__)


@dataclass
class _GuardEntry:
    guard: Any
    fail_closed: bool = False


class HookRegistry:
    """Event bus for daemon lifecycle hooks."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[..., Any]]] = {}
        self._guards: dict[str, list[_GuardEntry]] = {}

    def on(self, event: str, callback: Callable[..., Any]) -> None:
        """Register a callback for an event."""
        self._handlers.setdefault(event, []).append(callback)

    def off(self, event: str, callback: Callable[..., Any]) -> None:
        """Unregister a callback for an event."""
        handlers = self._handlers.get(event, [])
        if callback in handlers:
            handlers.remove(callback)

    def register_guard(
        self,
        phase: CyclePhase | str,
        guard: Any,
        *,
        fail_closed: bool = False,
    ) -> None:
        """Register a PhaseGuard for a specific cycle phase."""
        key = phase.value if hasattr(phase, "value") else str(phase)
        self._guards.setdefault(key, []).append(_GuardEntry(guard=guard, fail_closed=fail_closed))

    def unregister_guard(self, phase: CyclePhase | str, guard: Any) -> None:
        """Remove a PhaseGuard from a cycle phase."""
        key = phase.value if hasattr(phase, "value") else str(phase)
        guards = self._guards.get(key, [])
        for entry in list(guards):
            if entry.guard is guard:
                guards.remove(entry)

    async def check_guards(self, gate: PhaseGate) -> bool:
        """Run all guards for a phase.  Returns ``True`` if all allow, ``False`` if any veto."""
        key = gate.phase.value if hasattr(gate.phase, "value") else str(gate.phase)
        for entry in self._guards.get(key, []):
            guard = entry.guard
            try:
                result = guard.should_proceed(gate)
                if inspect.isawaitable(result):
                    result = await result
                if not result:
                    logger.info(
                        "Guard %s blocked phase %s for %s",
                        type(guard).__name__,
                        key,
                        gate.agent_id,
                    )
                    return False
            except Exception:
                if entry.fail_closed:
                    logger.exception(
                        "Guard %s failed for phase %s — blocking (fail-closed)",
                        type(guard).__name__,
                        key,
                    )
                    await self.emit(
                        "guard_failed",
                        guard=type(guard).__name__,
                        phase=key,
                        agent_id=gate.agent_id,
                        cycle_num=gate.cycle_num,
                    )
                    return False
                logger.exception(
                    "Guard %s failed for phase %s — allowing by default",
                    type(guard).__name__,
                    key,
                )
        return True

    async def emit(self, event: str, **kwargs: Any) -> None:
        """Fire all handlers for an event with kwargs."""
        snapshot = list(self._handlers.get(event, []))
        for handler in snapshot:
            try:
                result = handler(**kwargs)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("Hook handler failed for event %s", event)
