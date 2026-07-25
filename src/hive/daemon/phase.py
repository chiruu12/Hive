"""Formal cycle phases for the daemon heartbeat.

The daemon's per-agent cycle is divided into discrete phases.  Each phase
transition emits ``phase_enter`` and ``phase_exit`` hooks, enabling:

* Observability — external code can track exactly which phase an agent is in.
* Gating — ``PhaseGuard`` instances can veto entry into a phase.
* Metrics — phase durations can be measured via the timestamps.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class CyclePhase(enum.StrEnum):
    """Phases of a single agent cycle inside ``_run_agent_cycle_inner``."""

    #: Check whether the agent is parked waiting for human approval.
    APPROVAL_GATE = "approval_gate"

    #: Escalate suffering, detect crisis, possibly force-reset.
    SUFFERING_ESCALATION = "suffering_escalation"

    #: Load provider, profile, identity, memory, persona, mood.
    CONTEXT_ASSEMBLY = "context_assembly"

    #: Pursue the active goal (LLM call + tool execution).
    GOAL_PURSUIT = "goal_pursuit"

    #: Generate a new goal when none is active.
    GOAL_GENERATION = "goal_generation"

    #: Log suffering deltas, emit final events, return result.
    CLEANUP = "cleanup"


@dataclass
class PhaseGate:
    """Snapshot of a phase transition, passed to hooks and guards."""

    phase: CyclePhase
    agent_id: str
    cycle_num: int
    timestamp: float = field(default_factory=time.time)
