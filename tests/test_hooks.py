"""Tests for the daemon hook system."""

import pytest

from hive.daemon.hooks import HookRegistry


@pytest.fixture
def registry() -> HookRegistry:
    return HookRegistry()


@pytest.mark.asyncio
async def test_sync_callback_fires(registry: HookRegistry):
    captured: list[dict] = []

    def on_start(**kwargs):
        captured.append(kwargs)

    registry.on("cycle_start", on_start)
    await registry.emit("cycle_start", agent_id="a1", cycle_num=5)

    assert len(captured) == 1
    assert captured[0] == {"agent_id": "a1", "cycle_num": 5}


@pytest.mark.asyncio
async def test_async_callback_fires(registry: HookRegistry):
    captured: list[dict] = []

    async def on_end(**kwargs):
        captured.append(kwargs)

    registry.on("cycle_end", on_end)
    await registry.emit("cycle_end", agent_id="a1", cycle_num=3, result="completed")

    assert len(captured) == 1
    assert captured[0]["result"] == "completed"


@pytest.mark.asyncio
async def test_off_unregisters(registry: HookRegistry):
    captured: list[str] = []

    def handler(**kwargs):
        captured.append("fired")

    registry.on("goal_completed", handler)
    registry.off("goal_completed", handler)
    await registry.emit("goal_completed", agent_id="a1", goal_id="g1")

    assert len(captured) == 0


@pytest.mark.asyncio
async def test_multiple_handlers_fire_in_order(registry: HookRegistry):
    order: list[int] = []

    def first(**kwargs):
        order.append(1)

    def second(**kwargs):
        order.append(2)

    registry.on("cycle_start", first)
    registry.on("cycle_start", second)
    await registry.emit("cycle_start", agent_id="a1", cycle_num=0)

    assert order == [1, 2]


@pytest.mark.asyncio
async def test_emit_unregistered_event_is_noop(registry: HookRegistry):
    await registry.emit("nonexistent_event", data="hello")


@pytest.mark.asyncio
async def test_handler_exception_does_not_propagate(registry: HookRegistry):
    captured: list[str] = []

    def bad_handler(**kwargs):
        raise ValueError("boom")

    def good_handler(**kwargs):
        captured.append("ok")

    registry.on("cycle_start", bad_handler)
    registry.on("cycle_start", good_handler)
    await registry.emit("cycle_start", agent_id="a1", cycle_num=0)

    assert captured == ["ok"]


@pytest.mark.asyncio
async def test_off_nonexistent_handler_is_noop(registry: HookRegistry):
    def handler(**kwargs):
        pass

    registry.off("cycle_start", handler)


@pytest.mark.asyncio
async def test_mixed_sync_async_handlers(registry: HookRegistry):
    captured: list[str] = []

    def sync_handler(**kwargs):
        captured.append("sync")

    async def async_handler(**kwargs):
        captured.append("async")

    registry.on("suffering_changed", sync_handler)
    registry.on("suffering_changed", async_handler)
    await registry.emit("suffering_changed", agent_id="a1", suffering_state={})

    assert captured == ["sync", "async"]
