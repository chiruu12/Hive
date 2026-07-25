"""Unit tests for ToolkitFactory hardening (guardrails injection, tool_names cache)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hive.agents.delegation import DelegationEngine
from hive.config import GuardrailConfig
from hive.context import ExecutionContext
from hive.daemon.toolkit_factory import ToolkitFactory
from hive.interactions.a2a import A2AStore
from hive.memory.semantic import SemanticMemory
from hive.memory.store import HiveStore
from hive.runtime.guardrails import GuardrailPipeline, build_guardrail_pipeline
from hive.tools.notepad import NotepadManager
from hive.tools.sub_agents import SubAgentManager


@pytest.fixture
async def hive_store(tmp_path: Path) -> HiveStore:
    store = HiveStore(tmp_path / "hive.db")
    await store.initialize()
    return store


@pytest.fixture
def factory(tmp_path: Path, hive_store: HiveStore) -> ToolkitFactory:
    hive_dir = tmp_path / ".hive"
    hive_dir.mkdir()
    (hive_dir / "comms").mkdir()
    (hive_dir / "memory").mkdir()
    ctx = ExecutionContext(
        store=hive_store,
        comms_dir=hive_dir / "comms",
        memory_dir=hive_dir / "memory",
    )
    memory_cache: dict[str, SemanticMemory] = {}

    def get_memory(agent_id: str) -> SemanticMemory:
        if agent_id not in memory_cache:
            memory_cache[agent_id] = SemanticMemory(hive_dir / "memory", agent_id)
        return memory_cache[agent_id]

    return ToolkitFactory(
        hive_dir=hive_dir,
        ctx=ctx,
        store=hive_store,
        delegation=DelegationEngine(hive_store),
        notepad=NotepadManager(hive_dir / "notepads"),
        sub_agents=SubAgentManager(hive_store, hive_dir),
        a2a_store=A2AStore(hive_dir / "a2a"),
        economy_enabled=False,
        plugin_toolkits=[],
        get_memory=get_memory,
        guardrails=build_guardrail_pipeline(GuardrailConfig()),
    )


class TestGuardrailInjection:
    def test_build_does_not_rebuild_guardrails_from_config(
        self, factory: ToolkitFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sentinel = GuardrailPipeline([])
        factory._guardrails = sentinel
        calls: list[object] = []

        def _track(*args: object, **kwargs: object) -> GuardrailPipeline:
            calls.append(args)
            return GuardrailPipeline([])

        monkeypatch.setattr("hive.runtime.guardrails.build_guardrail_pipeline", _track)
        factory.build("agent-001", is_sub_agent=False)
        assert calls == []

    def test_comms_toolkit_receives_injected_guardrails(self, factory: ToolkitFactory) -> None:
        sentinel = MagicMock()
        sentinel.__bool__ = lambda self: True  # type: ignore[method-assign]
        factory._guardrails = sentinel
        toolkits = factory.build("agent-001", is_sub_agent=False)
        comms = next(tk for tk in toolkits if type(tk).__name__ == "CommsToolkit")
        assert comms._guardrails is sentinel  # noqa: SLF001


class TestToolNamesCache:
    def test_second_call_does_not_rebuild(self, factory: ToolkitFactory) -> None:
        with patch.object(factory, "_build_toolkits", wraps=factory._build_toolkits) as mock_build:
            first = factory.tool_names()
            second = factory.tool_names()
            assert first == second
            assert len(first) > 0
            mock_build.assert_called_once()

    def test_invalidate_forces_rebuild(self, factory: ToolkitFactory) -> None:
        factory.tool_names()
        factory.invalidate_tool_names_cache()
        with patch.object(factory, "_build_toolkits", wraps=factory._build_toolkits) as mock_build:
            factory.tool_names()
            mock_build.assert_called_once()

    def test_invalidate_clears_cache(self, factory: ToolkitFactory) -> None:
        factory.tool_names()
        assert factory._tool_names_cache is not None  # noqa: SLF001
        factory.invalidate_tool_names_cache()
        assert factory._tool_names_cache is None


class TestAgentToolkitCache:
    def test_build_reuses_same_instance(self, factory: ToolkitFactory) -> None:
        with patch.object(factory, "_build_toolkits", wraps=factory._build_toolkits) as mock_build:
            first = factory.build("agent-cache-1")
            second = factory.build("agent-cache-1")
            assert first is second
            mock_build.assert_called_once()

    def test_invalidate_agent_forces_rebuild(self, factory: ToolkitFactory) -> None:
        factory.build("agent-cache-2")
        factory.invalidate_agent_cache("agent-cache-2")
        with patch.object(factory, "_build_toolkits", wraps=factory._build_toolkits) as mock_build:
            factory.build("agent-cache-2")
            mock_build.assert_called_once()


class TestOrchestratorWorkspaceBinding:
    def test_orchestrator_toolkit_gets_agent_workspace(
        self, factory: ToolkitFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "hive.daemon.toolkit_factory.shutil.which",
            lambda _cmd: "/usr/bin/claude",
        )
        toolkits = factory.build("agent-001", is_sub_agent=False)
        orch = next(tk for tk in toolkits if type(tk).__name__ == "OrchestratorToolkit")
        expected = factory._hive_dir / "workspaces" / "agent-001"  # noqa: SLF001
        assert orch._agent_workspace == expected.resolve()  # noqa: SLF001


class TestSecureMinimalFactory:
    def test_comms_receives_guardrails(self, tmp_path: Path) -> None:
        from hive.config import GuardrailConfig
        from hive.daemon.secure_toolkit_factory import REST_MINIMAL_TOOLKIT_KEYS, build_minimal
        from hive.runtime.guardrails import build_guardrail_pipeline
        from hive.tools.comms import CommsToolkit

        hive_dir = tmp_path / ".hive"
        hive_dir.mkdir()
        (hive_dir / "comms").mkdir()
        (hive_dir / "agent_memory").mkdir()
        guardrails = build_guardrail_pipeline(GuardrailConfig())

        toolkits = build_minimal(
            hive_dir=hive_dir,
            agent_id="agent-rest",
            comms_dir=hive_dir / "comms",
            memory_dir=hive_dir / "agent_memory",
            guardrails=guardrails,
        )
        comms = next(tk for tk in toolkits if isinstance(tk, CommsToolkit))
        assert comms._guardrails is guardrails  # noqa: SLF001
        assert comms._agent_id == "agent-rest"  # noqa: SLF001
        assert REST_MINIMAL_TOOLKIT_KEYS == frozenset({"memory", "comms", "world"})

    def test_minimal_subset_excludes_shell(self, tmp_path: Path) -> None:
        from hive.config import GuardrailConfig
        from hive.daemon.secure_toolkit_factory import build_minimal
        from hive.runtime.guardrails import build_guardrail_pipeline

        hive_dir = tmp_path / ".hive"
        hive_dir.mkdir()
        (hive_dir / "comms").mkdir()
        (hive_dir / "agent_memory").mkdir()

        toolkits = build_minimal(
            hive_dir=hive_dir,
            agent_id="agent-rest",
            comms_dir=hive_dir / "comms",
            memory_dir=hive_dir / "agent_memory",
            guardrails=build_guardrail_pipeline(GuardrailConfig()),
        )
        names = {type(tk).__name__ for tk in toolkits}
        assert "ShellToolkit" not in names
        assert "WebToolkit" not in names
        assert "CommsToolkit" in names
        assert "MemoryToolkit" in names
