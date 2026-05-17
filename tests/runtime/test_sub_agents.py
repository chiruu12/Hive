"""Tests for SubAgentManager and SubAgentToolkit."""

from pathlib import Path

import pytest

from hive.agents.state import AgentState, AgentStatus
from hive.memory.store import HiveStore
from hive.tools.sub_agents import MAX_CHILDREN, SubAgentManager


@pytest.fixture
async def store(tmp_path: Path) -> HiveStore:
    s = HiveStore(tmp_path / "hive.db")
    await s.initialize()
    return s


@pytest.fixture
async def manager(store: HiveStore, tmp_path: Path) -> SubAgentManager:
    return SubAgentManager(store, tmp_path)


@pytest.fixture
async def parent_agent(store: HiveStore, tmp_path: Path) -> AgentState:
    state = AgentState(
        agent_id="parent-001",
        name="coder",
        role="Write code",
        model="test-model",
        status=AgentStatus.IDLE,
        workspace=str(tmp_path / "workspaces" / "parent-001"),
    )
    await store.save_agent(state)
    return state


class TestSubAgentManager:
    @pytest.mark.asyncio
    async def test_spawn_creates_agent(
        self, manager: SubAgentManager, store: HiveStore, parent_agent: AgentState
    ):
        child = await manager.spawn(
            parent_agent_id="parent-001",
            name="reviewer",
            role="Review code",
            task="Review sort.py",
        )
        assert child.agent_id.startswith("sub-reviewer-")
        assert child.spawned_by == "parent-001"
        assert child.max_cycles == 10

        stored = await store.get_agent(child.agent_id)
        assert stored is not None
        assert stored.spawned_by == "parent-001"

    @pytest.mark.asyncio
    async def test_spawn_sets_sub_agent_record(
        self, manager: SubAgentManager, store: HiveStore, parent_agent: AgentState
    ):
        child = await manager.spawn(
            parent_agent_id="parent-001",
            name="reviewer",
            role="Review code",
            task="Review sort.py",
        )
        sub = await store.get_sub_agent(child.agent_id)
        assert sub is not None
        assert sub["parent_agent_id"] == "parent-001"
        assert sub["task"] == "Review sort.py"
        assert sub["status"] == "running"

    @pytest.mark.asyncio
    async def test_depth_limit(
        self, manager: SubAgentManager, store: HiveStore, parent_agent: AgentState
    ):
        child1 = await manager.spawn(
            parent_agent_id="parent-001",
            name="sub1",
            role="helper",
            task="task 1",
        )
        child2 = await manager.spawn(
            parent_agent_id=child1.agent_id,
            name="sub2",
            role="helper",
            task="task 2",
        )
        assert child2.spawned_by == child1.agent_id

        with pytest.raises(ValueError, match="depth"):
            await manager.spawn(
                parent_agent_id=child2.agent_id,
                name="sub3",
                role="helper",
                task="task 3",
            )

    @pytest.mark.asyncio
    async def test_child_limit(
        self, manager: SubAgentManager, store: HiveStore, parent_agent: AgentState
    ):
        for i in range(MAX_CHILDREN):
            await manager.spawn(
                parent_agent_id="parent-001",
                name=f"child-{i}",
                role="helper",
                task=f"task {i}",
            )

        with pytest.raises(ValueError, match="children"):
            await manager.spawn(
                parent_agent_id="parent-001",
                name="extra",
                role="helper",
                task="one too many",
            )

    @pytest.mark.asyncio
    async def test_auto_kill_expired(
        self, manager: SubAgentManager, store: HiveStore, parent_agent: AgentState
    ):
        child = await manager.spawn(
            parent_agent_id="parent-001",
            name="temp",
            role="helper",
            task="short task",
            max_cycles=2,
        )
        await store.increment_cycles(child.agent_id)
        await store.increment_cycles(child.agent_id)

        killed = await manager.auto_kill_expired()
        assert child.agent_id in killed

        agent = await store.get_agent(child.agent_id)
        assert agent is not None
        assert agent.status == AgentStatus.DEAD

    @pytest.mark.asyncio
    async def test_terminate(
        self, manager: SubAgentManager, store: HiveStore, parent_agent: AgentState
    ):
        child = await manager.spawn(
            parent_agent_id="parent-001",
            name="doomed",
            role="helper",
            task="will be killed",
        )
        result = await manager.terminate(child.agent_id, "parent-001")
        assert "terminated" in result.lower()

        agent = await store.get_agent(child.agent_id)
        assert agent is not None
        assert agent.status == AgentStatus.DEAD

    @pytest.mark.asyncio
    async def test_result_relay(
        self, manager: SubAgentManager, store: HiveStore, parent_agent: AgentState
    ):
        child = await manager.spawn(
            parent_agent_id="parent-001",
            name="worker",
            role="helper",
            task="compute something",
        )
        await store.complete_sub_agent(child.agent_id, "The answer is 42.")
        result = await manager.get_result(child.agent_id)
        assert result == "The answer is 42."

    @pytest.mark.asyncio
    async def test_list_sub_agents(
        self, manager: SubAgentManager, store: HiveStore, parent_agent: AgentState
    ):
        await manager.spawn(
            parent_agent_id="parent-001", name="a", role="r", task="t1"
        )
        await manager.spawn(
            parent_agent_id="parent-001", name="b", role="r", task="t2"
        )
        children = await store.list_sub_agents("parent-001")
        assert len(children) == 2

    @pytest.mark.asyncio
    async def test_inherits_parent_model(
        self, manager: SubAgentManager, store: HiveStore, parent_agent: AgentState
    ):
        child = await manager.spawn(
            parent_agent_id="parent-001",
            name="kid",
            role="helper",
            task="something",
        )
        assert child.model == "test-model"
