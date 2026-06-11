"""Checkpointing — save and restore full agent state."""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from hive.agents.identity import AgentIdentity
from hive.agents.suffering import SufferingState
from hive.context import ExecutionContext

logger = logging.getLogger(__name__)


class Checkpoint(BaseModel):
    checkpoint_id: str
    agent_id: str
    label: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    suffering_snapshot: dict[str, Any] = {}
    goals_snapshot: list[dict[str, Any]] = []
    identity_snapshot: dict[str, Any] = {}
    world_snapshot: dict[str, Any] = {}
    persona_snapshot: dict[str, Any] = {}


class CheckpointManager:
    """Save, restore, list, and diff agent state checkpoints."""

    def __init__(self, hive_dir: Path):
        self._dir = hive_dir / "checkpoints"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _agent_dir(self, agent_id: str) -> Path:
        d = self._dir / agent_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(
        self,
        agent_id: str,
        label: str,
        suffering: SufferingState,
        identity: AgentIdentity | None,
        ctx: ExecutionContext,
        goals: list[dict[str, Any]] | None = None,
        persona_snapshot: dict[str, Any] | None = None,
    ) -> str:
        cp_id = f"cp-{uuid4().hex[:8]}"
        world_snap = {}
        if ctx.world is not None:
            try:
                fin = ctx.world.get_finances(agent_id)
                job = ctx.world.agent_job(agent_id)
                skills = ctx.world.get_skills(agent_id)
                world_snap = {
                    "balance": fin.balance,
                    "job": job.title if job else None,
                    "skills": [s.model_dump() for s in skills],
                }
            except Exception:
                # Checkpoint the rest of the agent's state anyway, but loudly:
                # a silently empty world snapshot breaks restart recovery for
                # economy scenarios.
                logger.warning(
                    "World snapshot failed for %s; checkpoint %s will omit world state",
                    agent_id,
                    cp_id,
                    exc_info=True,
                )

        cp = Checkpoint(
            checkpoint_id=cp_id,
            agent_id=agent_id,
            label=label,
            suffering_snapshot=suffering.model_dump(),
            goals_snapshot=goals or [],
            identity_snapshot=identity.model_dump() if identity else {},
            world_snapshot=world_snap,
            persona_snapshot=persona_snapshot or {},
        )

        path = self._agent_dir(agent_id) / f"{cp_id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(cp.model_dump_json(indent=2))
        tmp.rename(path)
        return cp_id

    def restore(self, agent_id: str, checkpoint_id: str) -> Checkpoint | None:
        path = self._agent_dir(agent_id) / f"{checkpoint_id}.json"
        if not path.exists():
            return None
        return Checkpoint.model_validate_json(path.read_text())

    def list_checkpoints(self, agent_id: str) -> list[Checkpoint]:
        agent_dir = self._agent_dir(agent_id)
        cps = []
        for f in sorted(agent_dir.glob("cp-*.json"), reverse=True):
            try:
                cps.append(Checkpoint.model_validate_json(f.read_text()))
            except Exception:
                # Quarantine instead of silently skipping: the file is preserved
                # for diagnosis but stops being re-parsed on every listing.
                quarantined = f.with_name(f.name + ".corrupt")
                try:
                    f.rename(quarantined)
                except OSError:
                    quarantined = f
                logger.warning(
                    "Corrupt checkpoint for %s quarantined as %s",
                    agent_id,
                    quarantined.name,
                    exc_info=True,
                )
        return cps

    def diff(self, cp_a: Checkpoint, cp_b: Checkpoint) -> dict[str, Any]:
        """Compare two checkpoints. Returns dict of what changed."""
        changes: dict[str, list[str]] = {"added": [], "removed": [], "modified": []}

        suf_a = cp_a.suffering_snapshot
        suf_b = cp_b.suffering_snapshot
        if suf_a.get("cumulative_load", 0) != suf_b.get("cumulative_load", 0):
            changes["modified"].append(
                f"suffering: {suf_a.get('cumulative_load', 0):.0%}"
                f" → {suf_b.get('cumulative_load', 0):.0%}"
            )

        goals_a = {g.get("goal_id") for g in cp_a.goals_snapshot}
        goals_b = {g.get("goal_id") for g in cp_b.goals_snapshot}
        for gid in goals_b - goals_a:
            changes["added"].append(f"goal: {gid}")
        for gid in goals_a - goals_b:
            changes["removed"].append(f"goal: {gid}")

        world_a = cp_a.world_snapshot
        world_b = cp_b.world_snapshot
        if world_a.get("balance") != world_b.get("balance"):
            changes["modified"].append(
                f"balance: ${world_a.get('balance', 0)} → ${world_b.get('balance', 0)}"
            )
        if world_a.get("job") != world_b.get("job"):
            changes["modified"].append(
                f"job: {world_a.get('job', 'none')} → {world_b.get('job', 'none')}"
            )

        persona_a = cp_a.persona_snapshot
        persona_b = cp_b.persona_snapshot
        persona_keys = (
            "risk_tolerance",
            "happiness",
            "concentration",
            "social_drive",
            "autonomy_level",
        )
        for key in persona_keys:
            val_a = persona_a.get(key)
            val_b = persona_b.get(key)
            if val_a is not None and val_b is not None and val_a != val_b:
                changes["modified"].append(f"persona.{key}: {val_a:.2f} → {val_b:.2f}")

        return changes
