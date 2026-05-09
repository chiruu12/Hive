"""Execution context — injected environment for all tools and actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from hive.memory.store import HiveStore

if TYPE_CHECKING:
    from hive.world.state import WorldState


@dataclass
class ExecutionContext:
    """Single source of injected state for tool execution."""

    store: HiveStore
    comms_dir: Path
    memory_dir: Path
    world: WorldState | None = field(default=None)

    def __post_init__(self) -> None:
        self.comms_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
