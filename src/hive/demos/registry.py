"""Demo registry — auto-discovers demo modules and exposes a unified interface."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DemoResult:
    """Outcome of running a demo."""

    name: str
    cycles: int
    agents: list[str]
    summary: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# ── Registry ──────────────────────────────────────────────────────────────────


@dataclass
class _DemoEntry:
    runner: Callable[..., DemoResult]
    description: str


_DEMOS: dict[str, _DemoEntry] = {}


def _register(name: str, runner: Callable[..., DemoResult], description: str) -> None:
    _DEMOS[name] = _DemoEntry(runner=runner, description=description)


def list_demos() -> dict[str, str]:
    """Return ``{name: description}`` for all registered demos."""
    _discover()
    return {name: entry.description for name, entry in _DEMOS.items()}


def run_demo(name: str, **kwargs: Any) -> DemoResult:
    """Run a demo by name.  Raises ``KeyError`` if not found."""
    _discover()
    if name not in _DEMOS:
        available = ", ".join(sorted(_DEMOS))
        raise KeyError(f"Unknown demo {name!r}. Available: {available}")
    return _DEMOS[name].runner(**kwargs)


def _discover() -> None:
    """Lazily register built-in demos."""
    if _DEMOS:
        return
    try:
        from hive.demos.survival import run_survival_demo

        _register(
            "survival",
            lambda **kw: _wrap_sync(run_survival_demo, "survival", **kw),
            "3 agents, 30 cycles, economy on. Watch them struggle.",
        )
    except ImportError:
        logger.debug("survival demo not available")

    try:
        from hive.demos.detective import run_detective_demo

        _register(
            "detective",
            lambda **kw: _wrap_sync(run_detective_demo, "detective", **kw),
            "Multi-model murder mystery with 3 detective personalities.",
        )
    except ImportError:
        logger.debug("detective demo not available")


def _wrap_sync(fn: Callable[..., Any], name: str, **kwargs: Any) -> DemoResult:
    """Wrap a synchronous demo function into a DemoResult."""
    fn(**kwargs)
    return DemoResult(
        name=name,
        cycles=kwargs.get("cycles", 0),
        agents=[],
        summary=f"Demo {name} completed.",
    )
