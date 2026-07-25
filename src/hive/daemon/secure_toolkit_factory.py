"""Secure-minimal toolkit factory for REST one-shot and documented daemon subset.

The REST task endpoints intentionally expose a smaller toolkit surface than the
full daemon heartbeat loop. This module centralizes that allowlist and ensures
guardrails are injected on every assembly path.
"""

from __future__ import annotations

from pathlib import Path

from hive.memory.semantic import SemanticMemory
from hive.runtime.guardrails import GuardrailPipeline
from hive.tools.base import Toolkit
from hive.tools.comms import CommsToolkit
from hive.tools.memory import MemoryToolkit

# Keys included in the REST one-shot minimal build. Daemon parent agents receive
# the full ToolkitFactory set; this list is intentionally smaller (no shell, web,
# sub_agents, orchestrator, etc.).
REST_MINIMAL_TOOLKIT_KEYS: frozenset[str] = frozenset({"memory", "comms", "world"})


def build_minimal(
    *,
    hive_dir: Path,
    agent_id: str,
    comms_dir: Path,
    memory_dir: Path,
    guardrails: GuardrailPipeline,
    unified_memory: bool = True,
    economy_enabled: bool = False,
) -> list[Toolkit]:
    """Build the agreed REST one-shot toolkit subset with guardrail injection."""
    toolkits: list[Toolkit] = []

    if unified_memory:
        semantic = SemanticMemory(hive_dir, agent_id)
        toolkits.append(
            MemoryToolkit(
                path=memory_dir,
                semantic=semantic,
                hive_dir=hive_dir,
            )
        )
    else:
        toolkits.append(MemoryToolkit(memory_dir, agent_id))

    toolkits.append(
        CommsToolkit(
            path=comms_dir,
            agent_id=agent_id,
            guardrails=guardrails,
        )
    )

    if economy_enabled:
        from hive.tools.world import WorldToolkit
        from hive.world.state import WorldState

        toolkits.insert(0, WorldToolkit(WorldState(hive_dir), agent_id))

    for tk in toolkits:
        tk.bind(agent_id)

    return toolkits
