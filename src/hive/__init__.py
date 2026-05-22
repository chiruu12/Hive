"""Hive - Autonomous agent OS."""

__version__ = "0.3.0"

from hive.agents.existence import ExistenceLoop
from hive.agents.goal_strategy import Goal, GoalContext, GoalStrategy
from hive.agents.profile import AgentProfile
from hive.agents.state import AgentState, AgentStatus
from hive.agents.suffering import StressorRegistry, StressorType, SufferingState
from hive.api import Hive
from hive.config import HiveConfig, load_config
from hive.context import ExecutionContext
from hive.daemon.hooks import HookRegistry
from hive.daemon.loop import HiveDaemon
from hive.daemon.setup import initialize_hive
from hive.interactions.registry import PatternRegistry
from hive.memory.backend import MemoryBackend
from hive.memory.events import EventLog, EventType, HiveEvent
from hive.memory.store import HiveStore
from hive.memory.tfidf_backend import TFIDFBackend
from hive.models.anthropic import Anthropic
from hive.models.base import BaseProvider
from hive.models.factory import create_runtime_provider
from hive.models.fireworks import Fireworks
from hive.models.groq import Groq
from hive.models.lmstudio import LMStudio
from hive.models.ollama import Ollama
from hive.models.openai import OpenAI
from hive.models.openrouter import OpenRouter
from hive.orchestrator import (
    ClaudeCodeSession,
    CodexSession,
    OrchestratorToolkit,
    SessionManager,
)
from hive.runtime import (
    Agent,
    ConversationMemory,
    DaemonAgentAdapter,
    GenerateResult,
    GoalOutcome,
    Instructions,
    Message,
    PersistentMemory,
    Persona,
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
    ToolkitAlreadyBoundError,
    ToolResult,
    Workflow,
    collect_tools,
    make_tool,
    tool,
)
from hive.tools.alarms import AlarmChecker, AlarmToolkit
from hive.tools.comms import CommsToolkit
from hive.tools.knowledge import KnowledgeToolkit
from hive.tools.mcp import MCPToolkit
from hive.tools.memory import MemoryToolkit
from hive.tools.tasks import TaskToolkit
from hive.tools.world import WorldToolkit
from hive.world.state import WorldState

__all__ = [
    "Agent",
    "AgentProfile",
    "AlarmChecker",
    "AlarmToolkit",
    "Anthropic",
    "ClaudeCodeSession",
    "CodexSession",
    "BaseProvider",
    "Hive",
    "AgentState",
    "AgentStatus",
    "CommsToolkit",
    "ConversationMemory",
    "DaemonAgentAdapter",
    "collect_tools",
    "Fireworks",
    "EventLog",
    "EventType",
    "ExecutionContext",
    "ExistenceLoop",
    "GenerateResult",
    "Goal",
    "GoalContext",
    "GoalOutcome",
    "GoalStrategy",
    "Groq",
    "Instructions",
    "HiveConfig",
    "HiveDaemon",
    "HookRegistry",
    "HiveEvent",
    "HiveStore",
    "KnowledgeToolkit",
    "LMStudio",
    "make_tool",
    "MCPToolkit",
    "MemoryBackend",
    "MemoryToolkit",
    "Message",
    "Ollama",
    "OpenAI",
    "OpenRouter",
    "OrchestratorToolkit",
    "PatternRegistry",
    "Persona",
    "PersistentMemory",
    "Step",
    "StressorRegistry",
    "StressorType",
    "StructuredGenerateResult",
    "StructuredTaskResult",
    "SufferingState",
    "Role",
    "SessionManager",
    "TFIDFBackend",
    "Task",
    "TaskResult",
    "TaskStatus",
    "TaskToolkit",
    "Tool",
    "ToolCall",
    "ToolResult",
    "Toolkit",
    "ToolkitAlreadyBoundError",
    "Workflow",
    "WorldState",
    "WorldToolkit",
    "create_runtime_provider",
    "initialize_hive",
    "load_config",
    "tool",
]
