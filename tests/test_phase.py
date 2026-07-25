"""Tests for CyclePhase, PhaseGate, PhaseGuard, and HookRegistry guard system."""

from __future__ import annotations

import pytest

from hive.daemon.gates import CostBudgetGuard, ManualPauseGuard
from hive.daemon.hooks import HookRegistry
from hive.daemon.phase import CyclePhase, PhaseGate

# ---------------------------------------------------------------------------
# CyclePhase enum
# ---------------------------------------------------------------------------


class TestCyclePhase:
    def test_expected_values(self):
        expected = {
            "approval_gate",
            "suffering_escalation",
            "context_assembly",
            "goal_pursuit",
            "goal_generation",
            "cleanup",
        }
        actual = {phase.value for phase in CyclePhase}
        assert actual == expected

    def test_is_str_enum(self):
        assert isinstance(CyclePhase.APPROVAL_GATE, str)
        assert CyclePhase.APPROVAL_GATE == "approval_gate"

    def test_six_phases(self):
        assert len(CyclePhase) == 6


# ---------------------------------------------------------------------------
# PhaseGate dataclass
# ---------------------------------------------------------------------------


class TestPhaseGate:
    def test_creation(self):
        gate = PhaseGate(
            phase=CyclePhase.GOAL_PURSUIT,
            agent_id="agent-1",
            cycle_num=42,
        )
        assert gate.phase == CyclePhase.GOAL_PURSUIT
        assert gate.agent_id == "agent-1"
        assert gate.cycle_num == 42
        assert isinstance(gate.timestamp, float)
        assert gate.timestamp > 0

    def test_timestamp_auto_generated(self):
        g1 = PhaseGate(phase=CyclePhase.CLEANUP, agent_id="a", cycle_num=1)
        g2 = PhaseGate(phase=CyclePhase.CLEANUP, agent_id="a", cycle_num=1)
        assert g1.timestamp <= g2.timestamp


# ---------------------------------------------------------------------------
# PhaseGuard protocol
# ---------------------------------------------------------------------------


class TestPhaseGuardProtocol:
    def test_manual_pause_guard_conforms(self):
        guard = ManualPauseGuard()
        assert hasattr(guard, "should_proceed")

    def test_cost_budget_guard_conforms(self):
        guard = CostBudgetGuard()
        assert hasattr(guard, "should_proceed")


# ---------------------------------------------------------------------------
# ManualPauseGuard
# ---------------------------------------------------------------------------


class TestManualPauseGuard:
    @pytest.mark.asyncio
    async def test_allows_when_not_paused(self):
        guard = ManualPauseGuard()
        gate = PhaseGate(phase=CyclePhase.GOAL_PURSUIT, agent_id="a", cycle_num=1)
        assert await guard.should_proceed(gate) is True

    @pytest.mark.asyncio
    async def test_blocks_when_paused(self):
        guard = ManualPauseGuard()
        guard.paused = True
        gate = PhaseGate(phase=CyclePhase.GOAL_PURSUIT, agent_id="a", cycle_num=1)
        assert await guard.should_proceed(gate) is False

    @pytest.mark.asyncio
    async def test_resume_allows_again(self):
        guard = ManualPauseGuard()
        gate = PhaseGate(phase=CyclePhase.CLEANUP, agent_id="a", cycle_num=1)
        guard.paused = True
        assert await guard.should_proceed(gate) is False
        guard.paused = False
        assert await guard.should_proceed(gate) is True


# ---------------------------------------------------------------------------
# CostBudgetGuard
# ---------------------------------------------------------------------------


class TestCostBudgetGuard:
    @pytest.mark.asyncio
    async def test_cost_budget_guard_blocks_without_tracker(self):
        guard = CostBudgetGuard(budget=None)
        gate = PhaseGate(phase=CyclePhase.GOAL_PURSUIT, agent_id="a", cycle_num=1)
        assert await guard.should_proceed(gate) is False

    @pytest.mark.asyncio
    async def test_allows_when_budget_not_exceeded(self):
        class FakeBudget:
            def is_exceeded(self):
                return False

            def is_at_capacity(self):
                return False

        guard = CostBudgetGuard(budget=FakeBudget())
        gate = PhaseGate(phase=CyclePhase.GOAL_PURSUIT, agent_id="a", cycle_num=1)
        assert await guard.should_proceed(gate) is True

    @pytest.mark.asyncio
    async def test_blocks_when_budget_exceeded(self):
        class FakeBudget:
            def is_exceeded(self):
                return True

            def is_at_capacity(self):
                return False

        guard = CostBudgetGuard(budget=FakeBudget())
        gate = PhaseGate(phase=CyclePhase.GOAL_PURSUIT, agent_id="a", cycle_num=1)
        assert await guard.should_proceed(gate) is False


# ---------------------------------------------------------------------------
# HookRegistry guard integration
# ---------------------------------------------------------------------------


class TestHookRegistryGuards:
    @pytest.mark.asyncio
    async def test_check_guards_allows_when_no_guards(self):
        registry = HookRegistry()
        gate = PhaseGate(phase=CyclePhase.GOAL_PURSUIT, agent_id="a", cycle_num=1)
        assert await registry.check_guards(gate) is True

    @pytest.mark.asyncio
    async def test_register_guard_blocks_phase(self):
        registry = HookRegistry()
        guard = ManualPauseGuard()
        guard.paused = True
        registry.register_guard(CyclePhase.GOAL_PURSUIT, guard)
        gate = PhaseGate(phase=CyclePhase.GOAL_PURSUIT, agent_id="a", cycle_num=1)
        assert await registry.check_guards(gate) is False

    @pytest.mark.asyncio
    async def test_register_guard_allows_other_phases(self):
        registry = HookRegistry()
        guard = ManualPauseGuard()
        guard.paused = True
        registry.register_guard(CyclePhase.GOAL_PURSUIT, guard)
        gate = PhaseGate(phase=CyclePhase.CLEANUP, agent_id="a", cycle_num=1)
        assert await registry.check_guards(gate) is True

    @pytest.mark.asyncio
    async def test_unregister_guard(self):
        registry = HookRegistry()
        guard = ManualPauseGuard()
        guard.paused = True
        registry.register_guard(CyclePhase.GOAL_PURSUIT, guard)
        registry.unregister_guard(CyclePhase.GOAL_PURSUIT, guard)
        gate = PhaseGate(phase=CyclePhase.GOAL_PURSUIT, agent_id="a", cycle_num=1)
        assert await registry.check_guards(gate) is True

    @pytest.mark.asyncio
    async def test_multiple_guards_all_must_pass(self):
        registry = HookRegistry()
        g1 = ManualPauseGuard()
        g2 = ManualPauseGuard()
        g2.paused = True
        registry.register_guard(CyclePhase.CLEANUP, g1)
        registry.register_guard(CyclePhase.CLEANUP, g2)
        gate = PhaseGate(phase=CyclePhase.CLEANUP, agent_id="a", cycle_num=1)
        assert await registry.check_guards(gate) is False

    @pytest.mark.asyncio
    async def test_guard_exception_allows_by_default(self):
        """A guard that raises should not block when fail_closed is unset."""
        registry = HookRegistry()

        class BadGuard:
            async def should_proceed(self, gate):
                raise RuntimeError("oops")

        registry.register_guard(CyclePhase.CLEANUP, BadGuard())
        gate = PhaseGate(phase=CyclePhase.CLEANUP, agent_id="a", cycle_num=1)
        assert await registry.check_guards(gate) is True

    @pytest.mark.asyncio
    async def test_guard_exception_blocks_when_fail_closed(self):
        """A guard that raises should block when fail_closed=True."""
        registry = HookRegistry()

        class BadGuard:
            async def should_proceed(self, gate):
                raise RuntimeError("oops")

        registry.register_guard(CyclePhase.CLEANUP, BadGuard(), fail_closed=True)
        gate = PhaseGate(phase=CyclePhase.CLEANUP, agent_id="a", cycle_num=1)
        assert await registry.check_guards(gate) is False

    @pytest.mark.asyncio
    async def test_guard_failed_event_emitted_on_fail_closed(self):
        registry = HookRegistry()
        events: list[dict[str, object]] = []

        async def on_guard_failed(**kwargs: object) -> None:
            events.append(kwargs)

        registry.on("guard_failed", on_guard_failed)

        class BadGuard:
            async def should_proceed(self, gate):
                raise RuntimeError("oops")

        registry.register_guard(CyclePhase.GOAL_PURSUIT, BadGuard(), fail_closed=True)
        gate = PhaseGate(phase=CyclePhase.GOAL_PURSUIT, agent_id="a", cycle_num=1)
        assert await registry.check_guards(gate) is False
        assert len(events) == 1
        assert events[0]["guard"] == "BadGuard"
        assert events[0]["phase"] == "goal_pursuit"

    @pytest.mark.asyncio
    async def test_phase_enter_emits_event(self):
        registry = HookRegistry()
        events = []

        async def on_enter(**kwargs):
            events.append(kwargs)

        registry.on("phase_enter", on_enter)
        await registry.emit(
            "phase_enter",
            phase=CyclePhase.GOAL_PURSUIT,
            agent_id="a",
            cycle_num=5,
        )
        assert len(events) == 1
        assert events[0]["phase"] == CyclePhase.GOAL_PURSUIT

    @pytest.mark.asyncio
    async def test_phase_exit_emits_event(self):
        registry = HookRegistry()
        events = []

        async def on_exit(**kwargs):
            events.append(kwargs)

        registry.on("phase_exit", on_exit)
        await registry.emit(
            "phase_exit",
            phase=CyclePhase.GOAL_PURSUIT,
            agent_id="a",
            cycle_num=5,
        )
        assert len(events) == 1
        assert events[0]["agent_id"] == "a"


# ---------------------------------------------------------------------------
# HiveDaemon guard wiring (stability-02)
# ---------------------------------------------------------------------------


class TestHiveDaemonGuards:
    def test_manual_pause_guard_registered_on_all_phases(self, tmp_path):
        from hive.config import HiveConfig, set_config
        from hive.daemon.loop import HiveDaemon
        from hive.daemon.phase import CyclePhase

        hive = tmp_path / ".hive"
        hive.mkdir()
        (hive / "sessions").mkdir()
        (hive / "workspaces").mkdir()
        (hive / "comms").mkdir()
        (hive / "agent_memory").mkdir()
        cfg = HiveConfig()
        cfg.economy.enabled = False
        set_config(cfg)
        cfg.save(hive)

        daemon = HiveDaemon(hive, heartbeat=60, logs_dir=tmp_path / "logs")
        for phase in CyclePhase:
            assert daemon.hooks._guards.get(phase.value)

    @pytest.mark.asyncio
    async def test_daemon_pause_blocks_goal_phase(self, tmp_path):
        from hive.config import HiveConfig, set_config
        from hive.daemon.loop import HiveDaemon

        hive = tmp_path / ".hive"
        hive.mkdir()
        (hive / "sessions").mkdir()
        (hive / "workspaces").mkdir()
        (hive / "comms").mkdir()
        (hive / "agent_memory").mkdir()
        cfg = HiveConfig()
        cfg.economy.enabled = False
        set_config(cfg)
        cfg.save(hive)

        daemon = HiveDaemon(hive, heartbeat=60, logs_dir=tmp_path / "logs")
        daemon.pause()
        gate = PhaseGate(phase=CyclePhase.GOAL_PURSUIT, agent_id="a", cycle_num=1)
        assert await daemon.hooks.check_guards(gate) is False
        daemon.resume()
        assert await daemon.hooks.check_guards(gate) is True
