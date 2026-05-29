"""Tests for safe toolkit binding (bind vs rebind)."""

from __future__ import annotations

import pytest

from hive.tools.base import Toolkit, ToolkitAlreadyBoundError, tool


class _DummyToolkit(Toolkit):
    @tool()
    def greet(self, name: str) -> str:
        """Say hello."""
        return f"Hello {name} from {self._agent_id}"


def test_bind_unbound_succeeds() -> None:
    tk = _DummyToolkit()
    tk.bind("agent-a")
    assert tk._agent_id == "agent-a"


def test_is_bound_property() -> None:
    tk = _DummyToolkit()
    assert not tk.is_bound
    tk.bind("agent-a")
    assert tk.is_bound


def test_bind_same_agent_is_idempotent() -> None:
    tk = _DummyToolkit()
    tk.bind("agent-a")
    tk.bind("agent-a")
    assert tk._agent_id == "agent-a"


def test_bind_different_agent_raises() -> None:
    tk = _DummyToolkit()
    tk.bind("agent-a")
    with pytest.raises(ToolkitAlreadyBoundError, match="already bound to 'agent-a'"):
        tk.bind("agent-b")


def test_rebind_unbound_succeeds() -> None:
    tk = _DummyToolkit()
    tk.rebind("agent-a")
    assert tk._agent_id == "agent-a"


def test_rebind_different_agent_succeeds() -> None:
    tk = _DummyToolkit()
    tk.bind("agent-a")
    tk.rebind("agent-b")
    assert tk._agent_id == "agent-b"


def test_rebind_same_agent_succeeds() -> None:
    tk = _DummyToolkit()
    tk.bind("agent-a")
    tk.rebind("agent-a")
    assert tk._agent_id == "agent-a"


def test_no_state_leakage_between_agents() -> None:
    """Two agents binding the same toolkit class get separate instances."""
    tk_a = _DummyToolkit()
    tk_b = _DummyToolkit()
    tk_a.bind("agent-a")
    tk_b.bind("agent-b")
    assert tk_a._agent_id == "agent-a"
    assert tk_b._agent_id == "agent-b"


def test_agent_constructor_binds_unbound_toolkits() -> None:
    """Agent.__init__ only binds unbound toolkits (doesn't raise on already-bound)."""
    from unittest.mock import AsyncMock

    from hive.runtime.agent import Agent

    tk = _DummyToolkit()
    Agent(name="test", model=AsyncMock(), toolkits=[tk])
    assert tk._agent_id == "test"


def test_agent_constructor_skips_already_bound() -> None:
    """Agent.__init__ skips toolkits already bound to the correct agent."""
    from unittest.mock import AsyncMock

    from hive.runtime.agent import Agent

    tk = _DummyToolkit()
    tk.bind("my-agent")
    Agent(name="my-agent", model=AsyncMock(), toolkits=[tk], agent_id="my-agent")
    assert tk._agent_id == "my-agent"


def test_rebind_then_bind_same_agent() -> None:
    """bind → rebind → bind(same) all succeed."""
    tk = _DummyToolkit()
    tk.bind("agent-a")
    tk.rebind("agent-b")
    tk.bind("agent-b")  # idempotent after rebind
    assert tk._agent_id == "agent-b"


def test_get_tools_is_cached() -> None:
    """get_tools() returns the same cached list across calls (A7a)."""
    tk = _DummyToolkit()
    first = tk.get_tools()
    second = tk.get_tools()
    assert first is second


def test_discover_tools_runs_once(monkeypatch) -> None:
    """_discover_tools is invoked only once even across many get_tools() calls."""
    tk = _DummyToolkit()
    calls = {"n": 0}
    real_discover = tk._discover_tools

    def counting_discover() -> list:
        calls["n"] += 1
        return real_discover()

    monkeypatch.setattr(tk, "_discover_tools", counting_discover)
    tk.get_tools()
    tk.get_tools()
    tk.get_tools()
    assert calls["n"] == 1


def test_bind_populates_cache() -> None:
    """bind() discovers tools eagerly so get_tools() reuses the cache."""
    tk = _DummyToolkit()
    assert tk._cached_tools is None
    tk.bind("agent-a")
    assert tk._cached_tools is not None
    assert tk.get_tools() is tk._cached_tools


def test_rebind_preserves_cache() -> None:
    """rebind() only swaps the agent id; the discovered tool list is unchanged."""
    tk = _DummyToolkit()
    tk.bind("agent-a")
    cached = tk.get_tools()
    tk.rebind("agent-b")
    assert tk.get_tools() is cached


@pytest.mark.asyncio
async def test_rebound_toolkit_tools_use_new_agent_id() -> None:
    """Tool calls reflect the rebound agent_id."""
    tk = _DummyToolkit()
    tk.bind("agent-a")
    greet = tk.get_tools()[0]
    result_a = await greet.call(name="world")
    assert "agent-a" in result_a

    tk.rebind("agent-b")
    result_b = await greet.call(name="world")
    assert "agent-b" in result_b
    assert "agent-a" not in result_b


@pytest.mark.asyncio
async def test_copy_resets_cache_so_clone_tools_bind_to_clone() -> None:
    """copy.copy() must not share the cached tools (bound to the original)."""
    import copy

    tk = _DummyToolkit()
    tk.bind("agent-a")
    tk.get_tools()  # populate the cache on the original

    clone = copy.copy(tk)
    clone.rebind("agent-b")
    # The clone's cached list is independent, and its tool runs against agent-b.
    assert clone._cached_tools is None or clone._cached_tools is not tk._cached_tools
    result = await clone.get_tools()[0].call(name="world")
    assert "agent-b" in result
    assert "agent-a" not in result


@pytest.mark.asyncio
async def test_agent_sharing_one_toolkit_instance_isolates_agent_id() -> None:
    """Two agents built from one already-bound toolkit don't cross-bind (A7a + copy)."""
    from unittest.mock import AsyncMock

    from hive.runtime.agent import Agent

    tk = _DummyToolkit()
    tk.bind("agent-a")
    Agent(name="agent-a", model=AsyncMock(), toolkits=[tk], agent_id="agent-a")
    agent_b = Agent(name="agent-b", model=AsyncMock(), toolkits=[tk], agent_id="agent-b")

    # agent_b got a clone; its tool must resolve agent-b, not agent-a.
    b_tool = agent_b.get_tools()[0]
    assert "agent-b" in await b_tool.call(name="x")
