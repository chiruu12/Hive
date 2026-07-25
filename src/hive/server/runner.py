"""Build and run a one-shot agent for the REST task endpoints.

Independent of the heartbeat loop: given a persisted agent, construct a runtime
``Agent`` (provider + a minimal toolkit set, mirroring ``lifecycle.spawn_agent``)
and run a single task. Wires the human-in-the-loop approval gate when enabled.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from hive.agents.approval import ApprovalPolicy, StoreApprovalGate
from hive.agents.profile import AgentProfile, resolve_profiles_dir
from hive.agents.state import AgentState
from hive.daemon.secure_toolkit_factory import build_minimal
from hive.models.factory import create_runtime_provider
from hive.runtime import Agent
from hive.runtime.guardrails import build_guardrail_pipeline
from hive.runtime.persona import Persona

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

    guardrails = build_guardrail_pipeline(ctx.config.guardrails)
    toolkits = build_minimal(
        hive_dir=ctx.hive_dir,
        agent_id=agent.agent_id,
        comms_dir=comms_dir,
        memory_dir=memory_dir,
        guardrails=guardrails,
        unified_memory=ctx.config.memory.unified,
        economy_enabled=ctx.config.economy.enabled,
    )

    approval_gate = None
    if ctx.config.approval.enabled:
        approval_gate = StoreApprovalGate(
            ctx.store,
            ApprovalPolicy(ctx.config.approval),
            agent.agent_id,
            session_id=session_id,
        )

    try:
        profile = AgentProfile.from_preset(agent.name, resolve_profiles_dir(ctx.hive_dir))
    except Exception:
        profile = None

    if profile is not None and profile.persona_config is not None:
        return Agent(
            name=agent.name,
            model=provider,
            persona=Persona.from_profile(profile),
            toolkits=toolkits,
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
        toolkits=toolkits,
        agent_id=agent.agent_id,
        on_text=on_text,
        approval_gate=approval_gate,
        guardrails=guardrails,
        tool_timeout=ctx.config.daemon.tool_timeout,
    )
