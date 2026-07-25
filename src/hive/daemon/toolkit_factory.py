"""Toolkit factory — builds the per-agent toolkit list for the daemon.

Extracted from :class:`HiveDaemon` to satisfy the Single Responsibility
Principle.  The daemon delegates toolkit construction entirely to this
factory, keeping ``_run_agent_cycle_inner`` focused on orchestration.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from pathlib import Path

from hive.agents.delegation import DelegationEngine
from hive.config import get_config
from hive.context import ExecutionContext
from hive.interactions.a2a import A2AStore
from hive.memory.protocol import StoreProtocol
from hive.memory.semantic import SemanticMemory
from hive.orchestrator.manager import SessionManager
from hive.runtime.guardrails import GuardrailPipeline
from hive.tools.a2a import A2AToolkit
from hive.tools.alarms import AlarmToolkit
from hive.tools.base import Toolkit
from hive.tools.clipboard import ClipboardToolkit
from hive.tools.comms import CommsToolkit
from hive.tools.delegation import DaemonDelegationToolkit
from hive.tools.file import FileToolkit
from hive.tools.git import GitToolkit
from hive.tools.knowledge import KnowledgeToolkit
from hive.tools.links import LinkToolkit
from hive.tools.memory import MemoryToolkit
from hive.tools.notepad import NotepadManager, NotepadToolkit
from hive.tools.schedule import ScheduleToolkit
from hive.tools.shell import ShellToolkit
from hive.tools.sub_agents import SubAgentManager, SubAgentToolkit
from hive.tools.tasks import TaskToolkit
from hive.tools.web import WebToolkit
from hive.tools.world import WorldToolkit

logger = logging.getLogger(__name__)

# Agent id used for one-time parent toolkit catalog scans (tool name discovery).
_CATALOG_AGENT_ID = "__tool_catalog__"

# Toolkit keys that re-enable high-risk privileges when listed in sub_agent_toolkits.
_RISKY_SUB_AGENT_TOOLKITS: frozenset[str] = frozenset(
    {"shell", "git", "delegation", "schedule", "orchestrator", "plugins", "world"}
)

# Secure default allowlist for sub-agents. Parent agents always get the full set.
# Excludes shell, git, delegation, schedule, orchestrator, world, and plugins —
# the highest-risk privilege-multiplication surfaces (H3).
DEFAULT_SUB_AGENT_TOOLKITS: frozenset[str] = frozenset(
    {
        "file",
        "memory",
        "notepad",
        "web",
        "knowledge",
        "links",
        "clipboard",
        "comms",
        "a2a",
        "task",
        "alarm",
        "sub_agents",
    }
)


class ToolkitFactory:
    """Builds and configures toolkits for each agent.

    Centralises all toolkit instantiation so the daemon doesn't need to
    import or know about individual toolkit classes.

    Guardrail config is fixed at daemon startup via the injected
    ``guardrails`` pipeline; changing guardrails requires a daemon restart.
    """

    def __init__(
        self,
        hive_dir: Path,
        ctx: ExecutionContext,
        store: StoreProtocol,
        delegation: DelegationEngine,
        notepad: NotepadManager,
        sub_agents: SubAgentManager,
        a2a_store: A2AStore,
        economy_enabled: bool,
        plugin_toolkits: list[type[Toolkit]],
        get_memory: Callable[[str], SemanticMemory],
        guardrails: GuardrailPipeline,
    ) -> None:
        self._hive_dir = hive_dir
        self._ctx = ctx
        self._store = store
        self._delegation = delegation
        self._notepad = notepad
        self._sub_agents = sub_agents
        self._a2a_store = a2a_store
        self._economy_enabled = economy_enabled
        self._plugin_toolkits = plugin_toolkits
        self._get_memory = get_memory
        self._guardrails = guardrails
        self._orch_manager: SessionManager | None = None
        self._tool_names_cache: list[str] | None = None
        self._agent_cache: dict[tuple[str, bool], list[Toolkit]] = {}

    def invalidate_tool_names_cache(self) -> None:
        """Clear cached parent tool names (call after hot-loading plugins)."""
        self._tool_names_cache = None
        self.invalidate_agent_cache()

    def invalidate_agent_cache(self, agent_id: str | None = None) -> None:
        """Drop cached toolkit lists (all agents, or one agent)."""
        if agent_id is None:
            self._agent_cache.clear()
            return
        for key in [k for k in self._agent_cache if k[0] == agent_id]:
            del self._agent_cache[key]

    def _allowed_keys(self, is_sub_agent: bool) -> frozenset[str] | None:
        """Return toolkit keys for sub-agents, or ``None`` for unrestricted parents."""
        if not is_sub_agent:
            return None
        cfg = get_config().tools
        if cfg.sub_agent_toolkits is not None:
            allowed = frozenset(cfg.sub_agent_toolkits)
            risky = allowed & _RISKY_SUB_AGENT_TOOLKITS
            if risky:
                logger.warning(
                    "tools.sub_agent_toolkits includes high-risk keys %s; "
                    "sub-agents will inherit elevated privileges",
                    sorted(risky),
                )
            return allowed
        return DEFAULT_SUB_AGENT_TOOLKITS

    def build(self, agent_id: str, *, is_sub_agent: bool = False) -> list[Toolkit]:
        """Build the toolkit list for an agent.

        Parent agents (``is_sub_agent=False``) receive every built-in toolkit.
        Sub-agents receive only keys in ``tools.sub_agent_toolkits``, or
        :data:`DEFAULT_SUB_AGENT_TOOLKITS` when that config is unset.

        When ``daemon.toolkit_cache`` is enabled (default), the built list is
        reused across heartbeat cycles until :meth:`invalidate_agent_cache` runs.
        """
        cache_key = (agent_id, is_sub_agent)
        cfg = get_config()
        if cfg.daemon.toolkit_cache and cache_key in self._agent_cache:
            return self._agent_cache[cache_key]

        toolkits = self._build_toolkits(agent_id, is_sub_agent=is_sub_agent)
        if cfg.daemon.toolkit_cache:
            self._agent_cache[cache_key] = toolkits
        return toolkits

    def _build_toolkits(self, agent_id: str, *, is_sub_agent: bool = False) -> list[Toolkit]:
        workspace = self._hive_dir / "workspaces" / agent_id
        workspace.mkdir(parents=True, exist_ok=True)

        allowed = self._allowed_keys(is_sub_agent)

        def include(key: str) -> bool:
            return allowed is None or key in allowed

        tools_cfg = get_config().tools
        guardrails = self._guardrails
        toolkits: list[Toolkit] = []

        if include("file"):
            toolkits.append(
                FileToolkit(
                    workspace=workspace,
                    max_read_bytes=tools_cfg.file_max_read_bytes,
                    max_write_bytes=tools_cfg.file_max_write_bytes,
                )
            )
        if include("shell"):
            toolkits.append(
                ShellToolkit(
                    workspace=workspace,
                    allow_dev_commands=tools_cfg.shell_allow_dev_commands,
                    pass_env=tools_cfg.shell_pass_env,
                )
            )
        if include("git"):
            toolkits.append(GitToolkit(workspace=workspace))
        if include("memory"):
            cfg = get_config()
            if cfg.memory.unified:
                toolkits.append(
                    MemoryToolkit(
                        path=self._ctx.memory_dir,
                        semantic=self._get_memory(agent_id),
                        hive_dir=self._hive_dir,
                    )
                )
            else:
                toolkits.append(MemoryToolkit(path=self._ctx.memory_dir))
        if include("comms"):
            toolkits.append(CommsToolkit(path=self._ctx.comms_dir, guardrails=guardrails))
        if include("delegation"):
            toolkits.append(
                DaemonDelegationToolkit(self._delegation, self._store, guardrails=guardrails)
            )
        if include("notepad"):
            toolkits.append(NotepadToolkit(manager=self._notepad))
        if include("sub_agents"):
            toolkits.append(
                SubAgentToolkit(
                    self._sub_agents,
                    self._store,
                    guardrails=guardrails,
                )
            )
        if include("a2a"):
            toolkits.append(A2AToolkit(self._a2a_store, self._store, guardrails=guardrails))
        if include("web"):
            toolkits.append(WebToolkit())
        if include("schedule"):
            toolkits.append(ScheduleToolkit(self._store, guardrails=guardrails))
        if include("task"):
            toolkits.append(TaskToolkit(self._store))
        if include("alarm"):
            toolkits.append(AlarmToolkit(self._store))
        if include("knowledge"):
            toolkits.append(KnowledgeToolkit(self._get_memory(agent_id)))
        if include("links"):
            toolkits.append(LinkToolkit(self._get_memory(agent_id)))
        if include("clipboard"):
            toolkits.append(ClipboardToolkit(store=self._store, memory=self._get_memory(agent_id)))

        if include("world") and self._economy_enabled and self._ctx.world is not None:
            toolkits.insert(0, WorldToolkit(self._ctx.world, agent_id))

        for tk in toolkits:
            tk.bind(agent_id)

        if include("plugins"):
            for tk_cls in self._plugin_toolkits:
                try:
                    plugin_tk = tk_cls()
                    plugin_tk.bind(agent_id)
                    toolkits.append(plugin_tk)
                except Exception as e:
                    logger.warning(
                        "Plugin toolkit %s failed for agent %s; skipping: %s",
                        tk_cls.__name__,
                        agent_id,
                        e,
                        exc_info=True,
                    )

        if include("orchestrator") and (shutil.which("claude") or shutil.which("codex")):
            from hive.orchestrator.toolkit import OrchestratorToolkit

            if self._orch_manager is None:
                self._orch_manager = SessionManager(self._hive_dir)
            orch_tk = OrchestratorToolkit(self._orch_manager, workspace=workspace)
            orch_tk.bind(agent_id)
            toolkits.append(orch_tk)

        return toolkits

    def tool_names(self) -> list[str]:
        """Return names of all tools from a sample parent-agent build.

        Result is cached until :meth:`invalidate_tool_names_cache` is called
        (e.g. after hot-loading plugin toolkits).
        """
        if self._tool_names_cache is not None:
            return self._tool_names_cache

        sample = self.build(_CATALOG_AGENT_ID, is_sub_agent=False)
        self._tool_names_cache = [t.name for tk in sample for t in tk.get_tools()]
        return self._tool_names_cache

    def tools_description(self, agent_id: str, *, is_sub_agent: bool = False) -> str:
        """Build a text description of available tools for goal prompts."""
        toolkits = self.build(agent_id, is_sub_agent=is_sub_agent)
        lines = []
        for tk in toolkits:
            for tool in tk.get_tools():
                lines.append(f"- {tool.name}: {tool.description}")
        return "\n".join(lines)
