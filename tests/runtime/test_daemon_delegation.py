"""Tests for DaemonDelegationToolkit — delegation exposed as agent tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from hive.agents.delegation import DelegationEngine
from hive.agents.state import AgentState, AgentStatus
from hive.memory.store import HiveStore
from hive.runtime.toolkits import DaemonDelegationToolkit


@pytest.fixture
async def store(tmp_path: Path) -> HiveStore:
    s = HiveStore(tmp_path / "test.db")
    await s.initialize()
    return s


@pytest.fixture
async def seeded_store(store: HiveStore) -> HiveStore:
    for aid, name, role in [
        ("coder-001", "coder", "developer"),
        ("reviewer-002", "reviewer", "code reviewer"),
        ("dead-003", "dead", "gone"),
    ]:
        status = AgentStatus.DEAD if aid == "dead-003" else AgentStatus.IDLE
        await store.save_agent(AgentState(
            agent_id=aid, name=name, role=role,
            model="mock", status=status, workspace=".",
        ))
    return store


@pytest.fixture
def toolkit(seeded_store: HiveStore) -> DaemonDelegationToolkit:
    engine = DelegationEngine(seeded_store)
    return DaemonDelegationToolkit(engine, "coder-001", seeded_store)


class TestDelegateTask:
    @pytest.mark.asyncio
    async def test_delegate_creates_goal(
        self, toolkit: DaemonDelegationToolkit, seeded_store: HiveStore,
    ) -> None:
        result = await toolkit.delegate_task("reviewer", "Review my PR")
        assert "Delegated to reviewer" in result
        assert "id=" in result

        goal = await seeded_store.get_active_goal("reviewer-002")
        assert goal is not None
        assert goal["objective"] == "Review my PR"

    @pytest.mark.asyncio
    async def test_delegate_nonexistent_agent(
        self, toolkit: DaemonDelegationToolkit,
    ) -> None:
        result = await toolkit.delegate_task("nobody", "Do something")
        assert "Agent not found: nobody" in result
        assert "reviewer" in result

    @pytest.mark.asyncio
    async def test_delegate_excludes_dead_agents(
        self, toolkit: DaemonDelegationToolkit,
    ) -> None:
        result = await toolkit.delegate_task("dead", "Revive")
        assert "Agent not found" in result

    @pytest.mark.asyncio
    async def test_delegate_excludes_self(
        self, toolkit: DaemonDelegationToolkit,
    ) -> None:
        result = await toolkit.delegate_task("coder", "Talk to myself")
        assert "Agent not found" in result


class TestCheckDelegation:
    @pytest.mark.asyncio
    async def test_check_existing(
        self, toolkit: DaemonDelegationToolkit,
    ) -> None:
        delegate_result = await toolkit.delegate_task(
            "reviewer", "Fix bugs",
        )
        did = delegate_result.split("id=")[1].split(")")[0]
        check_result = await toolkit.check_delegation(did)
        assert "Status: pending" in check_result

    @pytest.mark.asyncio
    async def test_check_nonexistent(
        self, toolkit: DaemonDelegationToolkit,
    ) -> None:
        result = await toolkit.check_delegation("del-nonexist")
        assert "not found" in result


class TestListPeers:
    @pytest.mark.asyncio
    async def test_lists_alive_peers(
        self, toolkit: DaemonDelegationToolkit,
    ) -> None:
        result = await toolkit.list_peers()
        assert "reviewer" in result
        assert "code reviewer" in result
        assert "dead" not in result
        assert "coder-001" not in result

    @pytest.mark.asyncio
    async def test_shows_goal_status(
        self, toolkit: DaemonDelegationToolkit,
        seeded_store: HiveStore,
    ) -> None:
        await seeded_store.save_goal(
            "g-1", "reviewer-002", "Reviewing code quality",
        )
        result = await toolkit.list_peers()
        assert "working on" in result
        assert "Reviewing code" in result

    @pytest.mark.asyncio
    async def test_no_peers(self, store: HiveStore) -> None:
        await store.save_agent(AgentState(
            agent_id="solo-001", name="solo", role="loner",
            model="mock", status=AgentStatus.IDLE, workspace=".",
        ))
        engine = DelegationEngine(store)
        tk = DaemonDelegationToolkit(engine, "solo-001", store)
        result = await tk.list_peers()
        assert "No other agents" in result
