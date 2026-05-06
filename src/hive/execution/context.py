"""Execution context — injected environment for all tools and actions."""

from dataclasses import dataclass
from pathlib import Path

from hive.memory.store import HiveStore
from hive.world.state import WorldState


@dataclass
class ExecutionContext:
    """Single source of injected state for tool execution.

    Created once by the daemon, passed to registry and all tools.
    Replaces module-level globals.
    """

    world: WorldState
    store: HiveStore
    comms_dir: Path
    memory_dir: Path

    def __post_init__(self) -> None:
        self.comms_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
