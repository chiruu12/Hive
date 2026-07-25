"""Swarm policy — controls how the daemon acts on swarm recommendations.

The :class:`SwarmPolicy` protocol lets operators choose between verbose
routing-hint logging (:class:`DefaultSwarmPolicy`) and quiet observability
(:class:`PassiveSwarmPolicy`). Neither policy mutates goals or routes tasks
autonomously — that remains a future product feature.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from hive.agents.specialization import SpecializationTracker
    from hive.agents.swarm import Recommendation

logger = logging.getLogger(__name__)


@runtime_checkable
class SwarmPolicy(Protocol):
    """Protocol for handling swarm recommendations."""

    async def handle_recommendation(
        self,
        rec: Recommendation,
        specialization: SpecializationTracker,
        agent_ids: list[str],
    ) -> None:
        """Act on a single recommendation."""
        ...


class DefaultSwarmPolicy:
    """Log routing hints from swarm recommendations (opt-in, no autonomous action).

    * ``routing`` — Logs a routing hint using ``SpecializationTracker.best_agent_for()``.
    * ``knowledge`` — Emits a warning log (no autonomous re-goaling).
    * ``specialization`` — Logs which agent is weak at which task type.
    """

    async def handle_recommendation(
        self,
        rec: Recommendation,
        specialization: SpecializationTracker,
        agent_ids: list[str],
    ) -> None:
        if rec.category == "routing":
            # Find the best agent for the target agent's typical task type.
            if rec.target_agent:
                best = specialization.best_agent_for("goal_pursuit", agent_ids)
                logger.info(
                    "Swarm routing: %s → %s (rec %s)",
                    rec.target_agent[:12],
                    best[:12] if best else "none",
                    rec.rec_id,
                )
        elif rec.category == "knowledge":
            logger.warning(
                "Swarm knowledge alert: %s (rec %s)",
                rec.description,
                rec.rec_id,
            )
        elif rec.category == "specialization":
            logger.info(
                "Swarm specialization: %s (rec %s)",
                rec.description,
                rec.rec_id,
            )
        else:
            logger.debug("Unknown recommendation category: %s", rec.category)


class PassiveSwarmPolicy:
    """Logs recommendations without taking action (backward-compatible)."""

    async def handle_recommendation(
        self,
        rec: Recommendation,
        specialization: SpecializationTracker,
        agent_ids: list[str],
    ) -> None:
        logger.debug(
            "Swarm rec [%s] (passive): %s",
            rec.category,
            rec.description,
        )
