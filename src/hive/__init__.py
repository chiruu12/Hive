"""Hive - Autonomous agent OS."""

__version__ = "0.1.0"

from hive.agents.existence import ExistenceLoop
from hive.agents.loop import AgentLoop
from hive.agents.profile import AgentProfile
from hive.agents.state import AgentState, AgentStatus
from hive.agents.suffering import StressorType, SufferingState
from hive.config import HiveConfig, load_config
from hive.daemon.loop import HiveDaemon
from hive.daemon.setup import initialize_hive
from hive.execution.action import Action, ActionResult, ToolAction, WorldAction
from hive.execution.context import ExecutionContext
from hive.execution.registry import ToolRegistry
from hive.memory.events import EventLog, EventType, HiveEvent
from hive.memory.store import HiveStore
from hive.world.state import WorldState

__all__ = [
    "AgentLoop",
    "AgentProfile",
    "AgentState",
    "AgentStatus",
    "Action",
    "ActionResult",
    "ExecutionContext",
    "EventLog",
    "EventType",
    "ExistenceLoop",
    "HiveConfig",
    "HiveDaemon",
    "HiveEvent",
    "HiveStore",
    "StressorType",
    "SufferingState",
    "ToolAction",
    "ToolRegistry",
    "WorldAction",
    "WorldState",
    "initialize_hive",
    "load_config",
]
