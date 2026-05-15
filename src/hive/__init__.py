"""Hive - Autonomous agent OS."""

__version__ = "0.2.0"

from hive.agents.existence import ExistenceLoop
from hive.agents.profile import AgentProfile
from hive.agents.state import AgentState, AgentStatus
from hive.agents.suffering import StressorType, SufferingState
from hive.api import Hive
from hive.config import HiveConfig, load_config
from hive.context import ExecutionContext
from hive.daemon.loop import HiveDaemon
from hive.daemon.setup import initialize_hive
from hive.mcp.client import MCPToolkit
from hive.memory.events import EventLog, EventType, HiveEvent
from hive.memory.store import HiveStore
from hive.models.base import BaseProvider
from hive.models.factory import create_runtime_provider
from hive.runtime import (
    Agent,
    CommsToolkit,
    ConversationMemory,
    DaemonAgentAdapter,
    GenerateResult,
    GoalOutcome,
    MemoryToolkit,
    Message,
    PersistentMemory,
    Role,
    Step,
    StructuredGenerateResult,
    StructuredTaskResult,
    Task,
    TaskResult,
    TaskStatus,
    Tool,
    ToolCall,
    Toolkit,
    ToolResult,
    Workflow,
    WorldToolkit,
    collect_tools,
    make_tool,
    tool,
)
from hive.world.state import WorldState

__all__ = [
    "Agent",
    "AgentProfile",
    "BaseProvider",
    "Hive",
    "AgentState",
    "AgentStatus",
    "CommsToolkit",
    "ConversationMemory",
    "DaemonAgentAdapter",
    "collect_tools",
    "EventLog",
    "EventType",
    "ExecutionContext",
    "ExistenceLoop",
    "GenerateResult",
    "GoalOutcome",
    "HiveConfig",
    "HiveDaemon",
    "HiveEvent",
    "HiveStore",
    "make_tool",
    "MCPToolkit",
    "MemoryToolkit",
    "Message",
    "PersistentMemory",
    "Step",
    "StressorType",
    "StructuredGenerateResult",
    "StructuredTaskResult",
    "SufferingState",
    "Role",
    "Task",
    "TaskResult",
    "TaskStatus",
    "Tool",
    "ToolCall",
    "ToolResult",
    "Toolkit",
    "Workflow",
    "WorldState",
    "WorldToolkit",
    "create_runtime_provider",
    "initialize_hive",
    "load_config",
    "tool",
]
