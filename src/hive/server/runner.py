"""Build and run a one-shot agent for the REST task endpoints.

Independent of the heartbeat loop: given a persisted agent, construct a runtime
``Agent`` (provider + a minimal toolkit set, mirroring ``lifecycle.spawn_agent``)
and run a single task. Wires the human-in-the-loop approval gate when enabled.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from hive.agents.approval import ApprovalPolicy, StoreApprovalGate
from hive.agents.profile import AgentProfile, default_profiles_dir
from hive.agents.state import AgentState
from hive.models.factory import create_runtime_provider
from hive.runtime import Agent
from hive.runtime.guardrails import build_guardrail_pipeline
from hive.runtime.persona import Persona
from hive.tools.comms import CommsToolkit
from hive.tools.memory import MemoryToolkit

if TYPE_CHECKING:
    from hive.server.deps import ServerContext


def build_oneshot_agent(
    ctx: ServerContext,
    agent: AgentState,
    session_id: str,
    on_text: Callable[[str], None] | None = None,
) -> Agent:
    """Construct a runtime Agent for ``agent`` bound to this server's stores."""
    provider = create_runtime_provider(agent.model)
    memory_dir = ctx.hive_dir / "agent_memory"
    comms_dir = ctx.hive_dir / "comms"

    toolkits: list[object] = [
        MemoryToolkit(memory_dir, agent.agent_id),
        CommsToolkit(comms_dir, agent.agent_id),
    ]
    if ctx.config.economy.enabled:
        from hive.tools.world import WorldToolkit
        from hive.world.state import WorldState

        toolkits.insert(0, WorldToolkit(WorldState(ctx.hive_dir), agent.agent_id))

    approval_gate = None
    if ctx.config.approval.enabled:
        approval_gate = StoreApprovalGate(
            ctx.store,
            ApprovalPolicy(ctx.config.approval),
            agent.agent_id,
            session_id=session_id,
        )
    guardrails = build_guardrail_pipeline(ctx.config.guardrails)

    try:
        profile = AgentProfile.from_preset(agent.name, default_profiles_dir())
    except Exception:
        profile = None

    if profile is not None and profile.persona_config is not None:
        return Agent(
            name=agent.name,
            model=provider,
            persona=Persona.from_profile(profile),
            toolkits=toolkits,  # type: ignore[arg-type]
            agent_id=agent.agent_id,
            on_text=on_text,
            approval_gate=approval_gate,
            guardrails=guardrails,
            tool_timeout=ctx.config.daemon.tool_timeout,
        )

    system_prompt = (
        profile.build_system_prompt(economy_enabled=ctx.config.economy.enabled)
        if profile is not None
        else f"You are {agent.name}, a {agent.role}."
    )
    return Agent(
        name=agent.name,
        model=provider,
        system_prompt=system_prompt,
        toolkits=toolkits,  # type: ignore[arg-type]
        agent_id=agent.agent_id,
        on_text=on_text,
        approval_gate=approval_gate,
        guardrails=guardrails,
        tool_timeout=ctx.config.daemon.tool_timeout,
    )
