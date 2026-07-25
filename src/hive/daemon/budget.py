"""Daemon-level cost budget tracker with kill-switch support.

Tracks aggregate spend (USD + tokens) across all agents.  When the budget
is exceeded, a callback fires (once) and :meth:`is_exceeded` returns ``True``
so the daemon can halt further LLM work.

In ``reserve`` mode (default), callers hold a reservation before LLM work so
concurrent agents cannot each pass a phase guard and overshoot the cap.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

logger = logging.getLogger(__name__)

BudgetMode = Literal["reserve", "record_only"]


@dataclass
class BudgetSummary:
    """Snapshot of current budget state."""

    budget_usd: float
    budget_tokens: int
    spent_usd: float
    spent_tokens: int
    reserved_usd: float
    reserved_tokens: int
    remaining_usd: float
    remaining_tokens: int
    exceeded: bool
    unlimited: bool
    mode: BudgetMode


@dataclass
class BudgetReservation:
    """Held capacity until commit or release."""

    id: str
    usd: float
    tokens: int
    noop: bool = field(default=False, repr=False)

    @classmethod
    def noop_reservation(cls) -> BudgetReservation:
        """Sentinel for ``record_only`` mode (no capacity held)."""
        return cls(id="", usd=0.0, tokens=0, noop=True)


class BudgetTracker:
    """Accumulates cost across a daemon run and fires a kill-switch callback.

    Args:
        budget_usd: Maximum USD spend.  ``0.0`` means unlimited.
        budget_tokens: Maximum token count.  ``0`` means unlimited.
        on_exceeded: Async or sync callback fired once when the budget is first
            exceeded.  Receives a :class:`BudgetSummary`.
        mode: ``reserve`` holds estimated capacity before LLM calls;
            ``record_only`` disables reservation (legacy overshoot window).
    """

    def __init__(
        self,
        budget_usd: float = 0.0,
        budget_tokens: int = 0,
        on_exceeded: Callable[..., Any] | None = None,
        mode: BudgetMode = "reserve",
    ) -> None:
        self._budget_usd = budget_usd
        self._budget_tokens = budget_tokens
        self._on_exceeded = on_exceeded
        self._mode: BudgetMode = mode
        self._spent_usd: float = 0.0
        self._spent_tokens: int = 0
        self._reserved_usd: float = 0.0
        self._reserved_tokens: int = 0
        self._exceeded_fired: bool = False
        self._lock = asyncio.Lock()

    @property
    def budget_usd(self) -> float:
        return self._budget_usd

    @property
    def budget_tokens(self) -> int:
        return self._budget_tokens

    @property
    def spent_usd(self) -> float:
        return self._spent_usd

    @property
    def spent_tokens(self) -> int:
        return self._spent_tokens

    @property
    def reserved_usd(self) -> float:
        return self._reserved_usd

    @property
    def reserved_tokens(self) -> int:
        return self._reserved_tokens

    @property
    def mode(self) -> BudgetMode:
        return self._mode

    @property
    def unlimited(self) -> bool:
        """True when both USD and token limits are disabled (``0``)."""
        return self._budget_usd <= 0 and self._budget_tokens <= 0

    async def reserve(
        self, estimate_usd: float = 0.0, estimate_tokens: int = 0
    ) -> BudgetReservation | None:
        """Hold estimated capacity before an LLM call.

        Returns ``None`` when the estimate cannot fit in remaining budget.
        In ``record_only`` mode always returns a no-op reservation.
        """
        if estimate_usd < 0:
            estimate_usd = 0.0
        if estimate_tokens < 0:
            estimate_tokens = 0
        if self._mode == "record_only":
            return BudgetReservation.noop_reservation()
        async with self._lock:
            if not self._fits(estimate_usd, estimate_tokens):
                return None
            self._reserved_usd += estimate_usd
            self._reserved_tokens += estimate_tokens
            return BudgetReservation(
                id=uuid4().hex,
                usd=estimate_usd,
                tokens=estimate_tokens,
            )

    async def commit(
        self,
        reservation: BudgetReservation | None,
        actual_usd: float = 0.0,
        actual_tokens: int = 0,
    ) -> None:
        """Release a reservation and record actual spend."""
        if actual_usd < 0:
            actual_usd = 0.0
        if actual_tokens < 0:
            actual_tokens = 0
        async with self._lock:
            if reservation is not None and not reservation.noop:
                self._reserved_usd = max(0.0, self._reserved_usd - reservation.usd)
                self._reserved_tokens = max(0, self._reserved_tokens - reservation.tokens)
            self._spent_usd += actual_usd
            self._spent_tokens += actual_tokens
            await self._maybe_fire_exceeded()

    async def release(self, reservation: BudgetReservation | None) -> None:
        """Return held capacity without recording spend."""
        if reservation is None or reservation.noop:
            return
        async with self._lock:
            self._reserved_usd = max(0.0, self._reserved_usd - reservation.usd)
            self._reserved_tokens = max(0, self._reserved_tokens - reservation.tokens)

    async def record(self, cost_usd: float = 0.0, tokens: int = 0) -> None:
        """Record a spend increment (no prior reservation)."""
        await self.commit(None, cost_usd, tokens)

    def is_exceeded(self) -> bool:
        """Return ``True`` if either budget limit has been exceeded."""
        if self._budget_usd > 0 and self._spent_usd >= self._budget_usd:
            return True
        if self._budget_tokens > 0 and self._spent_tokens >= self._budget_tokens:
            return True
        return False

    def is_at_capacity(self) -> bool:
        """Return ``True`` when no further reservations can be granted."""
        if self.unlimited:
            return False
        avail_usd, avail_tokens = self.available()
        if self._budget_usd > 0 and avail_usd <= 0:
            return True
        if self._budget_tokens > 0 and avail_tokens <= 0:
            return True
        return False

    def available(self) -> tuple[float, int]:
        """Return ``(available_usd, available_tokens)`` after spend and reservations."""
        if self._budget_usd > 0:
            usd = self._budget_usd - self._spent_usd - self._reserved_usd
        else:
            usd = float("inf")
        if self._budget_tokens > 0:
            tokens = self._budget_tokens - self._spent_tokens - self._reserved_tokens
        else:
            tokens = 2**53
        return usd, tokens

    def remaining(self) -> tuple[float, int]:
        """Return ``(remaining_usd, remaining_tokens)``. Negative = over budget."""
        return self.available()

    def summary(self) -> BudgetSummary:
        """Return a point-in-time snapshot."""
        rem_usd, rem_tokens = self.remaining()
        return BudgetSummary(
            budget_usd=self._budget_usd,
            budget_tokens=self._budget_tokens,
            spent_usd=self._spent_usd,
            spent_tokens=self._spent_tokens,
            reserved_usd=self._reserved_usd,
            reserved_tokens=self._reserved_tokens,
            remaining_usd=rem_usd,
            remaining_tokens=rem_tokens,
            exceeded=self.is_exceeded(),
            unlimited=self.unlimited,
            mode=self._mode,
        )

    async def reset(self) -> None:
        """Clear spent totals and in-flight reservations."""
        async with self._lock:
            self._spent_usd = 0.0
            self._spent_tokens = 0
            self._reserved_usd = 0.0
            self._reserved_tokens = 0
            self._exceeded_fired = False

    def load_from(self, path: Path) -> None:
        """Load persisted spend totals (best-effort)."""
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            self._spent_usd = float(data.get("spent_usd", 0.0))
            self._spent_tokens = int(data.get("spent_tokens", 0))
            self._exceeded_fired = self.is_exceeded()
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            logger.warning("Could not load budget ledger from %s", path, exc_info=True)

    def save_to(self, path: Path) -> None:
        """Persist spent totals atomically."""
        payload = {
            "spent_usd": self._spent_usd,
            "spent_tokens": self._spent_tokens,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(payload, fh, indent=2)
                fh.write("\n")
            os.replace(tmp, path)
        except OSError:
            logger.warning("Could not persist budget ledger to %s", path, exc_info=True)
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def _fits(self, estimate_usd: float, estimate_tokens: int) -> bool:
        if self.is_exceeded():
            return False
        avail_usd, avail_tokens = self.available()
        if self._budget_usd > 0 and estimate_usd > avail_usd:
            return False
        if self._budget_tokens > 0 and estimate_tokens > avail_tokens:
            return False
        return True

    async def _maybe_fire_exceeded(self) -> None:
        if not self._exceeded_fired and self.is_exceeded():
            self._exceeded_fired = True
            logger.warning(
                "Budget exceeded: spent $%.4f / $%.4f, %d / %d tokens",
                self._spent_usd,
                self._budget_usd,
                self._spent_tokens,
                self._budget_tokens,
            )
            if self._on_exceeded is not None:
                try:
                    result = self._on_exceeded(self.summary())
                    if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                        await result
                except Exception:
                    logger.exception("Budget exceeded callback failed")


def budget_ledger_path(hive_dir: Path) -> Path:
    """Path to the persisted spend ledger (``.hive/budget.json``)."""
    return hive_dir / "budget.json"


def read_budget_snapshot(hive_dir: Path) -> BudgetSummary:
    """Build a budget snapshot from config limits and optional ledger file."""
    from hive.config import HiveConfig

    cfg = HiveConfig.load(hive_dir)
    tracker = BudgetTracker(
        budget_usd=cfg.daemon.budget_usd,
        budget_tokens=cfg.daemon.budget_tokens,
        mode=cfg.daemon.budget_mode,
    )
    if cfg.daemon.budget_persist:
        tracker.load_from(budget_ledger_path(hive_dir))
    return tracker.summary()


def reset_budget_ledger(hive_dir: Path) -> None:
    """Clear spent counters in the persisted ledger (no-op when persist disabled)."""
    from hive.config import HiveConfig

    cfg = HiveConfig.load(hive_dir)
    if not cfg.daemon.budget_persist:
        return
    BudgetTracker().save_to(budget_ledger_path(hive_dir))


def budget_snapshot_to_dict(summary: BudgetSummary) -> dict[str, Any]:
    """Serialize :class:`BudgetSummary` for CLI/REST parity."""
    return {
        "budget_usd": summary.budget_usd,
        "budget_tokens": summary.budget_tokens,
        "spent_usd": round(summary.spent_usd, 6),
        "spent_tokens": summary.spent_tokens,
        "reserved_usd": round(summary.reserved_usd, 6),
        "reserved_tokens": summary.reserved_tokens,
        "remaining_usd": round(summary.remaining_usd, 6)
        if summary.remaining_usd != float("inf")
        else None,
        "remaining_tokens": summary.remaining_tokens if summary.remaining_tokens < 2**53 else None,
        "exceeded": summary.exceeded,
        "unlimited": summary.unlimited,
        "mode": summary.mode,
        "status": "unlimited (budget_usd=0)" if summary.unlimited else "limited",
    }
