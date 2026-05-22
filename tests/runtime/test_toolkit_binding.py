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
