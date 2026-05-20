"""Daemon hook system — register callbacks for lifecycle events."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class HookRegistry:
    """Event bus for daemon lifecycle hooks."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[..., Any]]] = {}

    def on(self, event: str, callback: Callable[..., Any]) -> None:
        """Register a callback for an event."""
        self._handlers.setdefault(event, []).append(callback)

    def off(self, event: str, callback: Callable[..., Any]) -> None:
        """Unregister a callback for an event."""
        handlers = self._handlers.get(event, [])
        if callback in handlers:
            handlers.remove(callback)

    async def emit(self, event: str, **kwargs: Any) -> None:
        """Fire all handlers for an event with kwargs."""
        for handler in self._handlers.get(event, []):
            try:
                result = handler(**kwargs)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Hook handler failed for event %s", event)
