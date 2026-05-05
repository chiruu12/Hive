"""Daemon lifecycle - spawn, kill, and manage agents."""

import asyncio
import logging
from pathlib import Path
from uuid import uuid4

from hive.agents.loop import AgentLoop
from hive.agents.profile import AgentProfile
from hive.agents.state import AgentState, AgentStatus
from hive.memory.events import EventLog
from hive.memory.store import HiveStore
from hive.models.router import create_provider

logger = logging.getLogger(__name__)

_running_agents: dict[str, AgentState] = {}


def _hive_dir() -> Path:
    return Path.cwd() / ".hive"


def _profiles_dir() -> Path:
    here = Path(__file__).resolve()
    return here.parent.parent.parent.parent / "profiles"


def spawn_agent(
    preset: str,
    task: str | None = None,
    model_override: str | None = None,
) -> AgentState:
    """Spawn a new agent from a preset profile."""
    profiles = _profiles_dir()
    profile = AgentProfile.from_preset(preset, profiles)

    if model_override:
        profile.model = model_override

    agent_id = f"{profile.name}-{uuid4().hex[:8]}"
    workspace = Path.cwd() / ".hive" / "workspaces" / agent_id
    workspace.mkdir(parents=True, exist_ok=True)

    state = AgentState(
        agent_id=agent_id,
        name=profile.name,
        role=profile.role,
        model=profile.model,
        status=AgentStatus.WORKING if task else AgentStatus.IDLE,
        current_task=task,
        workspace=str(workspace),
    )

    _running_agents[agent_id] = state

    hive_dir = _hive_dir()
    store = HiveStore(hive_dir / "hive.db")
    asyncio.run(store.save_agent(state))

    if task:
        event_log = EventLog(hive_dir)
        provider = create_provider(profile.model)

        loop = AgentLoop(
            agent_id=agent_id,
            profile=profile,
            provider=provider,
            store=store,
            event_log=event_log,
        )

        asyncio.run(loop.run(task, cwd=workspace))
        state.status = AgentStatus.IDLE
        state.current_task = None

    return state


def kill_agent(name_or_id: str) -> None:
    """Terminate a running agent."""
    agent_id = _resolve_agent_id(name_or_id)
    if not agent_id:
        raise ValueError(f"Agent not found: {name_or_id}")

    if agent_id in _running_agents:
        _running_agents[agent_id].status = AgentStatus.DEAD
        del _running_agents[agent_id]

    hive_dir = _hive_dir()
    db_path = hive_dir / "hive.db"
    if db_path.exists():
        store = HiveStore(db_path)
        asyncio.run(store.update_agent_status(agent_id, AgentStatus.DEAD))


def get_all_agents() -> list[AgentState]:
    """Return all currently tracked agent states."""
    hive_dir = _hive_dir()
    db_path = hive_dir / "hive.db"

    if not db_path.exists():
        return list(_running_agents.values())

    store = HiveStore(db_path)
    try:
        agents = asyncio.run(store.list_agents())
        for state in _running_agents.values():
            if not any(a.agent_id == state.agent_id for a in agents):
                agents.append(state)
        return agents
    except Exception:
        return list(_running_agents.values())


def _resolve_agent_id(name_or_id: str) -> str | None:
    if name_or_id in _running_agents:
        return name_or_id
    for aid, state in _running_agents.items():
        if state.name == name_or_id or aid.startswith(name_or_id):
            return aid
    return None
