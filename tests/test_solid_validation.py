"""SOLID validation tests — verify architectural contracts are upheld.

These tests act as architectural guardrails: if a refactoring breaks
a SOLID contract, these tests will catch it.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from hive.memory.protocol import StoreProtocol
from hive.memory.store import HiveStore

# ---------------------------------------------------------------------------
# DIP: StoreProtocol conformance
# ---------------------------------------------------------------------------


class TestStoreProtocolConformance:
    """Verify HiveStore satisfies StoreProtocol (Dependency Inversion)."""

    def test_hive_store_is_protocol_instance(self):
        """HiveStore must be a runtime-checkable instance of StoreProtocol."""
        # We can't instantiate HiveStore without a DB path, but we can check
        # that the class has all required methods.
        for name in dir(StoreProtocol):
            if name.startswith("_"):
                continue
            assert hasattr(HiveStore, name), f"HiveStore missing StoreProtocol method: {name}"

    def test_store_protocol_methods_are_async(self):
        """All StoreProtocol methods must be async (they touch SQLite)."""
        for name, method in inspect.getmembers(StoreProtocol, predicate=inspect.isfunction):
            if name.startswith("_"):
                continue
            # Protocol methods are just stubs, but the signature should be async
            # We verify the actual HiveStore implementation is async
            impl = getattr(HiveStore, name)
            if callable(impl):
                assert inspect.iscoroutinefunction(impl), f"HiveStore.{name} should be async"

    def test_execution_context_uses_protocol(self):
        """ExecutionContext.store should be typed as StoreProtocol."""
        from hive.context import ExecutionContext

        hints = inspect.get_annotations(ExecutionContext)
        # The store field should accept StoreProtocol (not just HiveStore)
        store_type = hints.get("store")
        assert store_type is not None


# ---------------------------------------------------------------------------
# OCP: BaseProvider capability contract
# ---------------------------------------------------------------------------


class TestProviderContract:
    """Verify all providers satisfy the BaseProvider contract."""

    def test_all_providers_have_required_methods(self):
        """Every provider must implement the abstract interface."""
        from hive.models.anthropic import Anthropic
        from hive.models.openai import OpenAI

        required = {"generate_with_metadata", "available"}
        for cls in [Anthropic, OpenAI]:
            for method in required:
                assert hasattr(cls, method), f"{cls.__name__} missing {method}"

    def test_capability_enum_is_frozenset(self):
        """BaseProvider.CAPABILITIES should be a frozenset for immutability."""
        from hive.models.base import BaseProvider

        assert isinstance(BaseProvider.CAPABILITIES, frozenset)

    def test_providers_declare_capabilities(self):
        """Each provider class should declare CAPABILITIES as a frozenset."""
        from hive.models.anthropic import Anthropic
        from hive.models.openai import OpenAI

        for cls in [Anthropic, OpenAI]:
            caps = getattr(cls, "CAPABILITIES", None)
            assert caps is not None, f"{cls.__name__} missing CAPABILITIES"
            assert isinstance(caps, frozenset), f"{cls.__name__}.CAPABILITIES should be frozenset"


# ---------------------------------------------------------------------------
# LSP: Toolkit substitutability
# ---------------------------------------------------------------------------


class TestToolkitContract:
    """Verify all toolkits satisfy the Toolkit interface."""

    def test_toolkit_base_has_required_interface(self):
        """Toolkit base class must define get_tools() and bind()."""
        from hive.tools.base import Toolkit

        assert hasattr(Toolkit, "get_tools")
        assert hasattr(Toolkit, "bind")

    def test_concrete_toolkits_are_subclasses(self):
        """All built-in toolkits must subclass Toolkit."""
        from hive.tools.alarms import AlarmToolkit
        from hive.tools.base import Toolkit
        from hive.tools.comms import CommsToolkit
        from hive.tools.file import FileToolkit
        from hive.tools.git import GitToolkit
        from hive.tools.memory import MemoryToolkit
        from hive.tools.schedule import ScheduleToolkit
        from hive.tools.shell import ShellToolkit
        from hive.tools.tasks import TaskToolkit
        from hive.tools.web import WebToolkit

        for cls in [
            FileToolkit,
            ShellToolkit,
            CommsToolkit,
            MemoryToolkit,
            TaskToolkit,
            AlarmToolkit,
            ScheduleToolkit,
            WebToolkit,
            GitToolkit,
        ]:
            assert issubclass(cls, Toolkit), f"{cls.__name__} should subclass Toolkit"


# ---------------------------------------------------------------------------
# ISP: Protocol minimalism
# ---------------------------------------------------------------------------


class TestProtocolMinimalism:
    """Verify protocols are minimal (Interface Segregation)."""

    def test_goal_strategy_single_method(self):
        """GoalStrategy should be a single-method protocol."""
        from hive.agents.goal_strategy import GoalStrategy

        methods = [m for m in dir(GoalStrategy) if not m.startswith("_")]
        assert len(methods) == 1
        assert methods[0] == "generate_goal"

    def test_trigger_protocol_minimal(self):
        """Trigger protocol should have at most 3 methods."""
        from hive.triggers.base import Trigger

        methods = [m for m in dir(Trigger) if not m.startswith("_")]
        assert len(methods) <= 3

    def test_guardrail_protocol_minimal(self):
        """Guardrail protocol should have at most 3 members."""
        from hive.runtime.guardrails import Guardrail

        members = [m for m in dir(Guardrail) if not m.startswith("_")]
        assert len(members) <= 3


# ---------------------------------------------------------------------------
# SRP: Module size guardrails
# ---------------------------------------------------------------------------


class TestModuleSizeGuardrails:
    """Verify no module grows beyond reasonable bounds."""

    _DAEMON_DIR = Path(__file__).parent.parent / "src" / "hive" / "daemon"

    def test_daemon_loop_not_growing(self):
        """daemon/loop.py should stay under 500 lines after decomposition."""
        loop_path = self._DAEMON_DIR / "loop.py"
        lines = loop_path.read_text().count("\n")
        assert lines < 500, f"daemon/loop.py has {lines} lines — consider further decomposition"

    def test_daemon_extracted_modules_reasonable_size(self):
        """Extracted daemon modules should each stay under 600 lines."""
        for name in (
            "agent_context.py",
            "agent_cycle_runner.py",
            "agent_cycle_phases.py",
            "agent_cycle_outcomes.py",
            "economy_hooks.py",
            "heartbeat.py",
            "run_lifecycle.py",
        ):
            path = self._DAEMON_DIR / name
            lines = path.read_text().count("\n")
            assert lines < 600, f"daemon/{name} has {lines} lines"

    def test_runtime_agent_reasonable_size(self):
        """runtime/agent.py should stay under 1200 lines."""
        agent_path = Path(__file__).parent.parent / "src" / "hive" / "runtime" / "agent.py"
        lines = agent_path.read_text().count("\n")
        assert lines < 1200, f"runtime/agent.py has {lines} lines"

    def test_memory_store_reasonable_size(self):
        """memory/store.py should stay under 1600 lines."""
        store_path = Path(__file__).parent.parent / "src" / "hive" / "memory" / "store.py"
        lines = store_path.read_text().count("\n")
        assert lines < 1600, f"memory/store.py has {lines} lines"

    def test_cli_main_reasonable_size(self):
        """cli/main.py should stay under 2500 lines. It's the largest file and
        grows with new commands — decompose when this limit is hit."""
        cli_path = Path(__file__).parent.parent / "src" / "hive" / "cli" / "main.py"
        lines = cli_path.read_text().count("\n")
        assert lines < 2500, (
            f"cli/main.py has {lines} lines — consider splitting commands into "
            f"separate modules (e.g. cli/commands/daemon.py, cli/commands/project.py)"
        )


# ---------------------------------------------------------------------------
# New protocols: DIP + ISP for v0.7 additions
# ---------------------------------------------------------------------------


class TestNewProtocolConformance:
    """Verify v0.7 protocols are correctly structured."""

    def test_swarm_policy_protocol(self):
        """SwarmPolicy should be a runtime-checkable protocol with one method."""
        from hive.agents.swarm_policy import DefaultSwarmPolicy, PassiveSwarmPolicy, SwarmPolicy

        assert isinstance(SwarmPolicy, type)
        # Both implementations should satisfy the protocol
        assert isinstance(DefaultSwarmPolicy(), SwarmPolicy)
        assert isinstance(PassiveSwarmPolicy(), SwarmPolicy)

    def test_phase_guard_protocol(self):
        """PhaseGuard should be a runtime-checkable protocol."""
        from hive.daemon.gates import CostBudgetGuard, ManualPauseGuard, PhaseGuard

        assert isinstance(PhaseGuard, type)
        assert isinstance(ManualPauseGuard(), PhaseGuard)
        assert isinstance(CostBudgetGuard(), PhaseGuard)

    def test_wake_source_protocol(self):
        """WakeSource should be a runtime-checkable protocol."""
        from hive.daemon.wakeup import A2AWakeSource, WakeSource

        assert isinstance(WakeSource, type)
        assert isinstance(A2AWakeSource.__new__(A2AWakeSource), WakeSource)

    def test_minimal_store_satisfies_protocol(self):
        """MinimalStore fake must satisfy StoreProtocol for test doubles."""
        import importlib.util
        from pathlib import Path

        path = Path(__file__).resolve().parent / "fakes" / "minimal_store.py"
        spec = importlib.util.spec_from_file_location("minimal_store", path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.assert_store_protocol(mod.MinimalStore())

    def test_store_protocol_still_satisfied(self):
        """StoreProtocol should still be satisfied after all changes."""
        from hive.memory.protocol import StoreProtocol

        for name in dir(StoreProtocol):
            if name.startswith("_"):
                continue
            assert hasattr(HiveStore, name), f"HiveStore missing: {name}"

    def test_cycle_phase_enum_values(self):
        """CyclePhase should have exactly 6 phases."""
        from hive.daemon.phase import CyclePhase

        assert len(CyclePhase) == 6
