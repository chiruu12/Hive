"""Adversarial tests: daemon resilience under stress.

These tests probe the daemon's behavior under adversarial conditions:
- Rapid stop/start cycles
- Concurrent agent failures
- Budget exhaustion
- Phase guard behavior
- Resource cleanup
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from hive.agents.goal_strategy import GeneratedGoal, GoalContext
from hive.agents.state import AgentState, AgentStatus
from hive.config import HiveConfig, set_config
from hive.daemon.budget import BudgetTracker
from hive.daemon.gates import CostBudgetGuard, ManualPauseGuard
from hive.daemon.hooks import HookRegistry
from hive.daemon.loop import HiveDaemon
from hive.daemon.phase import CyclePhase, PhaseGate
from hive.memory.store import HiveStore

# ── Budget Tracker Adversarial ───────────────────────────────────────────────


class TestBudgetTrackerAdversarial:
    """Stress-test the budget tracker."""

    @pytest.mark.asyncio
    async def test_concurrent_record_calls(self):
        """Multiple concurrent record() calls should not corrupt state."""
        tracker = BudgetTracker(budget_usd=1.0, budget_tokens=1000)

        async def spend(amount):
            await tracker.record(cost_usd=amount, tokens=10)

        # Fire 100 concurrent spends
        await asyncio.gather(*[spend(0.001) for _ in range(100)])

        assert abs(tracker.spent_usd - 0.1) < 0.001
        assert tracker.spent_tokens == 1000

    @pytest.mark.asyncio
    async def test_budget_exceeded_fires_callback_once(self):
        """The on_exceeded callback should fire exactly once."""
        call_count = 0

        def on_exceeded(summary):
            nonlocal call_count
            call_count += 1

        tracker = BudgetTracker(budget_usd=1.0, on_exceeded=on_exceeded)

        # Cross the threshold multiple times
        await tracker.record(cost_usd=0.5)
        await tracker.record(cost_usd=0.6)
        await tracker.record(cost_usd=0.7)

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_negative_spend_is_clamped(self):
        """Negative spend is clamped to zero."""
        tracker = BudgetTracker(budget_usd=1.0)
        await tracker.record(cost_usd=-0.5, tokens=-10)
        assert tracker.spent_usd == 0.0
        assert tracker.spent_tokens == 0

    @pytest.mark.asyncio
    async def test_zero_budget_means_unlimited(self):
        """Zero budget should mean unlimited."""
        tracker = BudgetTracker(budget_usd=0.0, budget_tokens=0)
        assert not tracker.is_exceeded()

        await tracker.record(cost_usd=999999.0, tokens=999999)
        assert not tracker.is_exceeded()

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_propagate(self):
        """If the callback raises, the record() should not propagate it."""

        def bad_callback(summary):
            raise RuntimeError("callback exploded")

        tracker = BudgetTracker(budget_usd=1.0, on_exceeded=bad_callback)

        # Should not raise
        await tracker.record(cost_usd=2.0)
        assert tracker.is_exceeded()


# ── Phase Guard Adversarial ──────────────────────────────────────────────────


class TestPhaseGuardAdversarial:
    """Stress-test phase guards."""

    @pytest.mark.asyncio
    async def test_guard_exception_allows_by_default(self):
        """Third-party guards without fail_closed still fail open on exceptions."""

        class BrokenGuard:
            async def should_proceed(self, gate):
                raise RuntimeError("guard exploded")

        hooks = HookRegistry()
        hooks.register_guard(CyclePhase.GOAL_PURSUIT, BrokenGuard())

        gate = PhaseGate(phase=CyclePhase.GOAL_PURSUIT, agent_id="test", cycle_num=1)
        result = await hooks.check_guards(gate)
        assert result is True  # Fail-open for extension guards

    @pytest.mark.asyncio
    async def test_guard_exception_blocks_when_fail_closed(self):
        """Built-in safety guards with fail_closed=True block on exceptions."""

        class BrokenGuard:
            async def should_proceed(self, gate):
                raise RuntimeError("guard exploded")

        hooks = HookRegistry()
        hooks.register_guard(CyclePhase.GOAL_PURSUIT, BrokenGuard(), fail_closed=True)

        gate = PhaseGate(phase=CyclePhase.GOAL_PURSUIT, agent_id="test", cycle_num=1)
        result = await hooks.check_guards(gate)
        assert result is False

    @pytest.mark.asyncio
    async def test_cost_budget_guard_fail_closed_on_exception(self):
        """CostBudgetGuard registered fail-closed blocks when is_exceeded() raises."""

        class BrokenBudget:
            def is_exceeded(self):
                raise RuntimeError("tracker broken")

        hooks = HookRegistry()
        guard = CostBudgetGuard(BrokenBudget())
        hooks.register_guard(CyclePhase.GOAL_PURSUIT, guard, fail_closed=True)

        gate = PhaseGate(phase=CyclePhase.GOAL_PURSUIT, agent_id="test", cycle_num=1)
        assert await hooks.check_guards(gate) is False

    @pytest.mark.asyncio
    async def test_multiple_guards_all_must_pass(self):
        """If any guard vetoes, the phase should be blocked."""

        class AllowGuard:
            async def should_proceed(self, gate):
                return True

        class DenyGuard:
            async def should_proceed(self, gate):
                return False

        hooks = HookRegistry()
        hooks.register_guard(CyclePhase.GOAL_PURSUIT, AllowGuard())
        hooks.register_guard(CyclePhase.GOAL_PURSUIT, DenyGuard())

        gate = PhaseGate(phase=CyclePhase.GOAL_PURSUIT, agent_id="test", cycle_num=1)
        result = await hooks.check_guards(gate)
        assert result is False

    @pytest.mark.asyncio
    async def test_manual_pause_guard(self):
        """ManualPauseGuard should block when paused."""
        guard = ManualPauseGuard()
        gate = PhaseGate(phase=CyclePhase.GOAL_PURSUIT, agent_id="test", cycle_num=1)

        assert await guard.should_proceed(gate) is True

        guard.paused = True
        assert await guard.should_proceed(gate) is False

        guard.paused = False
        assert await guard.should_proceed(gate) is True

    @pytest.mark.asyncio
    async def test_cost_budget_guard_blocks_on_exceeded(self):
        """CostBudgetGuard should block when budget is exceeded."""
        tracker = BudgetTracker(budget_usd=1.0)
        guard = CostBudgetGuard(tracker)

        gate = PhaseGate(phase=CyclePhase.GOAL_PURSUIT, agent_id="test", cycle_num=1)
        assert await guard.should_proceed(gate) is True

        await tracker.record(cost_usd=2.0)
        assert await guard.should_proceed(gate) is False


# ── Hook Registry Adversarial ────────────────────────────────────────────────


class TestHookRegistryAdversarial:
    """Stress-test the hook registry."""

    @pytest.mark.asyncio
    async def test_handler_exception_does_not_break_emit(self):
        """If a handler raises, other handlers should still run."""
        call_log = []

        def good_handler(**kwargs):
            call_log.append("good")

        def bad_handler(**kwargs):
            call_log.append("bad")
            raise RuntimeError("handler exploded")

        hooks = HookRegistry()
        hooks.on("test_event", bad_handler)
        hooks.on("test_event", good_handler)

        await hooks.emit("test_event")

        assert "bad" in call_log
        assert "good" in call_log

    @pytest.mark.asyncio
    async def test_unregister_nonexistent_handler_noop(self):
        """Unregistering a handler that wasn't registered should not crash."""
        hooks = HookRegistry()
        hooks.off("test_event", lambda **kw: None)  # Should not raise

    @pytest.mark.asyncio
    async def test_emit_with_no_handlers(self):
        """Emitting an event with no handlers should not crash."""
        hooks = HookRegistry()
        await hooks.emit("nonexistent_event")  # Should not raise


# ── Daemon integration (stability-01 regressions) ───────────────────────────


class _FixedSpendStrategy:
    """GoalStrategy stub that always reports fixed spend without an objective."""

    def __init__(self, cost_usd: float, tokens: int = 10) -> None:
        self._cost_usd = cost_usd
        self._tokens = tokens

    async def generate_goal(self, context: GoalContext) -> GeneratedGoal:
        return GeneratedGoal(objective=None, cost_usd=self._cost_usd, tokens=self._tokens)


@pytest.fixture
def hive_dir(tmp_path: Path) -> Path:
    hive = tmp_path / ".hive"
    hive.mkdir()
    (hive / "sessions").mkdir()
    (hive / "workspaces").mkdir()
    (hive / "comms").mkdir()
    (hive / "agent_memory").mkdir()

    cfg = HiveConfig()
    cfg.economy.enabled = False
    cfg.daemon.budget_usd = 1.0
    set_config(cfg)
    cfg.save(hive)
    return hive


async def _seed_agent(store: HiveStore, agent_id: str, name: str = "researcher") -> AgentState:
    state = AgentState(
        agent_id=agent_id,
        name=name,
        role="research assistant",
        model="mock-model",
        status=AgentStatus.IDLE,
        workspace=".",
    )
    await store.save_agent(state)
    return state


class TestDaemonIntegrationAdversarial:
    """Thin HiveDaemon tests that must stay in the adversarial merge gate."""

    @pytest.mark.asyncio
    async def test_concurrent_agent_cycles_isolate_failures(self, hive_dir: Path) -> None:
        """One agent's cycle failure must not break asyncio.gather for siblings."""
        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        agent_ok = await _seed_agent(store, "agent-ok")
        agent_bad = await _seed_agent(store, "agent-bad", name="broken")

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")

        async def _mock_run_cycle(agent: AgentState) -> str:
            if agent.agent_id == "agent-bad":
                raise RuntimeError("simulated cycle failure")
            return "completed"

        daemon._run_agent_cycle = _mock_run_cycle  # type: ignore[method-assign]

        sem = asyncio.Semaphore(2)
        results = await asyncio.gather(
            daemon._run_agent_cycle_guarded(agent_ok, 0, sem),
            daemon._run_agent_cycle_guarded(agent_bad, 0, sem),
        )
        assert results[0] == "completed"
        assert results[1] is None

    @pytest.mark.asyncio
    async def test_exceeded_budget_blocks_agent_cycle(self, hive_dir: Path) -> None:
        """Pre-exceeded budget must return guarded before goal work runs."""
        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        agent = await _seed_agent(store, "researcher-test0001")

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")
        await daemon.budget.record(cost_usd=1.0)

        assert daemon.budget_exceeded is True
        result = await daemon._run_agent_cycle(agent)
        assert result == "guarded"

    @pytest.mark.asyncio
    async def test_kill_switch_set_on_budget_exceed(self, hive_dir: Path) -> None:
        """on_exceeded wiring must flip daemon.budget_exceeded exactly once."""
        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        await _seed_agent(store, "researcher-test0001")

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")

        assert daemon.budget_exceeded is False
        await daemon.budget.record(cost_usd=0.5)
        assert daemon.budget_exceeded is False
        await daemon.budget.record(cost_usd=0.6)
        assert daemon.budget_exceeded is True

    @pytest.mark.asyncio
    async def test_concurrent_goal_generation_hard_ceiling(self, hive_dir: Path) -> None:
        """Reservation prevents concurrent cycles from overshooting the daemon budget."""
        cfg = HiveConfig()
        cfg.economy.enabled = False
        cfg.daemon.budget_usd = 0.10
        cfg.daemon.budget_reserve_usd_generation = 0.06
        set_config(cfg)
        cfg.save(hive_dir)

        per_generation = 0.06
        epsilon = 0.001
        strategy = _FixedSpendStrategy(cost_usd=per_generation, tokens=5)

        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        agents = [await _seed_agent(store, f"agent-{i}", name=f"agent-{i}") for i in range(4)]

        daemon = HiveDaemon(
            hive_dir,
            heartbeat=0,
            logs_dir=hive_dir.parent / "logs",
            goal_strategy=strategy,
        )

        sem = asyncio.Semaphore(4)
        await asyncio.gather(*[daemon._run_agent_cycle_guarded(agent, 0, sem) for agent in agents])

        assert daemon.budget.spent_usd <= 0.10 + epsilon
        assert per_generation <= daemon.budget.spent_usd <= per_generation + epsilon

    @pytest.mark.asyncio
    async def test_daemon_pause_blocks_agent_cycle(self, hive_dir: Path) -> None:
        """Daemon-wide ManualPauseGuard must block cycles independently of agent status."""
        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        agent = await _seed_agent(store, "researcher-test0001")

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")
        daemon.pause()

        result = await daemon._run_agent_cycle(agent)
        assert result == "guarded"

        daemon.resume()
        gate = PhaseGate(phase=CyclePhase.GOAL_PURSUIT, agent_id=agent.agent_id, cycle_num=1)
        assert await daemon.hooks.check_guards(gate) is True
