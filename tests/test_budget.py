"""Tests for BudgetTracker — daemon-level cost kill switch."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from hive.agents.profile import AgentProfile
from hive.agents.state import AgentState, AgentStatus
from hive.config import HiveConfig, set_config
from hive.daemon.budget import BudgetSummary, BudgetTracker
from hive.daemon.loop import HiveDaemon
from hive.memory.store import HiveStore


class TestBudgetTracker:
    @pytest.mark.asyncio
    async def test_record_accumulates(self):
        tracker = BudgetTracker(budget_usd=10.0, budget_tokens=1000)
        await tracker.record(cost_usd=1.5, tokens=100)
        await tracker.record(cost_usd=2.0, tokens=200)
        assert tracker.spent_usd == 3.5
        assert tracker.spent_tokens == 300

    @pytest.mark.asyncio
    async def test_is_exceeded_usd(self):
        tracker = BudgetTracker(budget_usd=5.0)
        assert tracker.is_exceeded() is False
        await tracker.record(cost_usd=5.0)
        assert tracker.is_exceeded() is True

    @pytest.mark.asyncio
    async def test_is_exceeded_tokens(self):
        tracker = BudgetTracker(budget_tokens=100)
        assert tracker.is_exceeded() is False
        await tracker.record(tokens=100)
        assert tracker.is_exceeded() is True

    @pytest.mark.asyncio
    async def test_unlimited_when_zero(self):
        tracker = BudgetTracker(budget_usd=0.0, budget_tokens=0)
        await tracker.record(cost_usd=999999, tokens=999999)
        assert tracker.is_exceeded() is False

    @pytest.mark.asyncio
    async def test_remaining(self):
        tracker = BudgetTracker(budget_usd=10.0, budget_tokens=1000)
        await tracker.record(cost_usd=3.0, tokens=400)
        usd, tokens = tracker.remaining()
        assert usd == 7.0
        assert tokens == 600

    @pytest.mark.asyncio
    async def test_remaining_unlimited(self):
        tracker = BudgetTracker()
        usd, tokens = tracker.remaining()
        assert usd == float("inf")

    @pytest.mark.asyncio
    async def test_record_rejects_negative_values(self):
        tracker = BudgetTracker(budget_usd=10.0, budget_tokens=1000)
        await tracker.record(cost_usd=-1.0, tokens=-50)
        assert tracker.spent_usd == 0.0
        assert tracker.spent_tokens == 0

    @pytest.mark.asyncio
    async def test_callback_fires_once(self):
        calls = []

        async def on_exceeded(summary: BudgetSummary):
            calls.append(summary)

        tracker = BudgetTracker(budget_usd=2.0, on_exceeded=on_exceeded)
        await tracker.record(cost_usd=2.0)
        assert len(calls) == 1
        assert calls[0].exceeded is True
        # Second record should NOT fire again
        await tracker.record(cost_usd=1.0)
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_callback_sync(self):
        calls = []

        def on_exceeded(summary: BudgetSummary):
            calls.append(summary)

        tracker = BudgetTracker(budget_usd=1.0, on_exceeded=on_exceeded)
        await tracker.record(cost_usd=1.5)
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_propagate(self):
        def bad_callback(summary):
            raise RuntimeError("oops")

        tracker = BudgetTracker(budget_usd=1.0, on_exceeded=bad_callback)
        # Should not raise
        await tracker.record(cost_usd=2.0)
        assert tracker.is_exceeded() is True

    def test_summary(self):
        tracker = BudgetTracker(budget_usd=10.0, budget_tokens=500)
        s = tracker.summary()
        assert isinstance(s, BudgetSummary)
        assert s.budget_usd == 10.0
        assert s.spent_usd == 0.0
        assert s.remaining_usd == 10.0
        assert s.exceeded is False

    def test_properties(self):
        tracker = BudgetTracker(budget_usd=5.0, budget_tokens=100)
        assert tracker.budget_usd == 5.0
        assert tracker.budget_tokens == 100
        assert tracker.spent_usd == 0.0
        assert tracker.spent_tokens == 0


class TestBudgetReservation:
    @pytest.mark.asyncio
    async def test_reserve_blocks_second_concurrent_holder(self):
        tracker = BudgetTracker(budget_usd=0.10, mode="reserve")
        first = await tracker.reserve(0.06, 5)
        second = await tracker.reserve(0.06, 5)
        assert first is not None
        assert second is None
        assert tracker.reserved_usd == 0.06

    @pytest.mark.asyncio
    async def test_commit_releases_reservation_and_records_actual(self):
        tracker = BudgetTracker(budget_usd=1.0, mode="reserve")
        reservation = await tracker.reserve(0.10, 50)
        assert reservation is not None
        await tracker.commit(reservation, 0.08, 40)
        assert tracker.spent_usd == 0.08
        assert tracker.spent_tokens == 40
        assert tracker.reserved_usd == 0.0

    @pytest.mark.asyncio
    async def test_release_returns_capacity(self):
        tracker = BudgetTracker(budget_usd=0.10, mode="reserve")
        reservation = await tracker.reserve(0.06, 5)
        assert reservation is not None
        await tracker.release(reservation)
        again = await tracker.reserve(0.06, 5)
        assert again is not None

    @pytest.mark.asyncio
    async def test_record_only_skips_reservation_hold(self):
        tracker = BudgetTracker(budget_usd=0.10, mode="record_only")
        r1 = await tracker.reserve(0.06, 5)
        r2 = await tracker.reserve(0.06, 5)
        assert r1 is not None and r1.noop
        assert r2 is not None and r2.noop
        assert tracker.reserved_usd == 0.0

    @pytest.mark.asyncio
    async def test_is_at_capacity_when_fully_reserved(self):
        tracker = BudgetTracker(budget_usd=0.10, mode="reserve")
        assert tracker.is_at_capacity() is False
        reservation = await tracker.reserve(0.10, 0)
        assert reservation is not None
        assert tracker.is_at_capacity() is True

    @pytest.mark.asyncio
    async def test_persist_round_trip(self, tmp_path: Path):
        ledger = tmp_path / "budget.json"
        tracker = BudgetTracker(budget_usd=5.0)
        await tracker.record(cost_usd=1.25, tokens=10)
        tracker.save_to(ledger)

        reloaded = BudgetTracker(budget_usd=5.0)
        reloaded.load_from(ledger)
        assert reloaded.spent_usd == 1.25
        assert reloaded.spent_tokens == 10

    @pytest.mark.asyncio
    async def test_reset_clears_spend(self):
        tracker = BudgetTracker(budget_usd=1.0)
        await tracker.record(cost_usd=1.0)
        assert tracker.is_exceeded()
        await tracker.reset()
        assert tracker.spent_usd == 0.0
        assert tracker.is_exceeded() is False

    def test_summary_includes_unlimited_flag(self):
        tracker = BudgetTracker(budget_usd=0.0, budget_tokens=0)
        s = tracker.summary()
        assert s.unlimited is True
        assert s.mode == "reserve"


class TestDaemonBudgetIntegration:
    @pytest.fixture
    def hive_dir(self, tmp_path: Path) -> Path:
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

    async def _seed_agent(self, store: HiveStore) -> AgentState:
        state = AgentState(
            agent_id="researcher-test0001",
            name="researcher",
            role="research assistant",
            model="mock-model",
            status=AgentStatus.IDLE,
            workspace=".",
        )
        await store.save_agent(state)
        return state

    @pytest.mark.asyncio
    async def test_exceeded_budget_returns_guarded(self, hive_dir: Path) -> None:
        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        agent = await self._seed_agent(store)
        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")

        await daemon.budget.record(cost_usd=1.0)
        assert daemon.budget_exceeded is True

        result = await daemon._run_agent_cycle(agent)
        assert result == "guarded"

    @pytest.mark.asyncio
    async def test_on_exceeded_fires_once_via_daemon(self, hive_dir: Path) -> None:
        store = HiveStore(hive_dir / "hive.db")
        await store.initialize()
        await self._seed_agent(store)
        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")

        await daemon.budget.record(cost_usd=0.5)
        assert daemon.budget_exceeded is False
        await daemon.budget.record(cost_usd=0.6)
        assert daemon.budget_exceeded is True

    @pytest.mark.asyncio
    async def test_unlimited_budget_never_exceeds(self, hive_dir: Path) -> None:
        cfg = HiveConfig()
        cfg.economy.enabled = False
        cfg.daemon.budget_usd = 0.0
        cfg.daemon.budget_tokens = 0
        set_config(cfg)
        cfg.save(hive_dir)

        daemon = HiveDaemon(hive_dir, heartbeat=0, logs_dir=hive_dir.parent / "logs")
        await daemon.budget.record(cost_usd=999999.0, tokens=999999)
        assert daemon.budget.is_exceeded() is False
        assert daemon.budget_exceeded is False
        usd, tokens = daemon.budget.remaining()
        assert usd == float("inf")

    @pytest.mark.asyncio
    async def test_life_event_records_spend(self, tmp_path: Path, monkeypatch) -> None:
        """Life-event LLM calls increment BudgetTracker spend."""
        from typing import Any

        from hive.models.base import BaseProvider
        from hive.runtime.types import GenerateResult, Message
        from hive.world.events import Choice, LifeEvent

        cfg = HiveConfig()
        cfg.economy.enabled = True
        cfg.daemon.budget_usd = 10.0
        set_config(cfg)

        hive = tmp_path / ".hive"
        hive.mkdir()
        (hive / "sessions").mkdir()
        (hive / "workspaces").mkdir()
        cfg.save(hive)

        class _SpendProvider(BaseProvider):
            def __init__(self) -> None:
                super().__init__("mock")

            @property
            def available(self) -> bool:
                return True

            async def generate_with_metadata(self, *a: Any, **k: Any) -> GenerateResult:
                return GenerateResult(
                    message=Message.assistant("1"),
                    model="mock",
                    input_tokens=30,
                    output_tokens=20,
                    cost_usd=0.05,
                )

            async def generate_structured(self, *a: Any, **k: Any) -> Any:
                raise NotImplementedError

        daemon = HiveDaemon(hive, heartbeat=0, logs_dir=tmp_path / "logs")
        assert daemon._event_engine is not None
        await daemon._store.initialize()
        agent = AgentState(agent_id="a1", name="ada", role="t", model="m", status=AgentStatus.IDLE)
        await daemon._store.save_agent(agent)
        daemon._identity.load_or_create("a1", AgentProfile(name="ada", role="t"))

        event = LifeEvent(
            event_id="loss",
            name="Big Loss",
            description="You lost big.",
            category="financial",
            choices=[Choice(id="accept", description="Accept it")],
        )
        monkeypatch.setattr(daemon._event_engine, "roll_events", lambda aid, c: [event])
        monkeypatch.setattr("hive.daemon.loop.create_runtime_provider", lambda m: _SpendProvider())

        assert daemon.budget.spent_usd == 0.0
        assert daemon.budget.spent_tokens == 0
        await daemon._process_life_events([agent])
        assert daemon.budget.spent_usd == 0.05
        assert daemon.budget.spent_tokens == 50

    @pytest.mark.asyncio
    async def test_goal_generation_records_spend(self, tmp_path: Path, monkeypatch) -> None:
        """Existence-loop goal generation increments BudgetTracker spend."""
        from typing import Any

        from hive.models.base import BaseProvider
        from hive.runtime.types import GenerateResult, Message

        cfg = HiveConfig()
        cfg.economy.enabled = False
        cfg.daemon.budget_usd = 10.0
        set_config(cfg)

        hive = tmp_path / ".hive"
        hive.mkdir()
        (hive / "sessions").mkdir()
        (hive / "workspaces").mkdir()
        (hive / "comms").mkdir()
        (hive / "agent_memory").mkdir()
        cfg.save(hive)

        class _GoalProvider(BaseProvider):
            def __init__(self) -> None:
                super().__init__("mock")

            @property
            def available(self) -> bool:
                return True

            async def generate_with_metadata(self, *a: Any, **k: Any) -> GenerateResult:
                return GenerateResult(
                    message=Message.assistant(
                        '{"goal": "Analyze quarterly metrics", "reasoning": "needed"}'
                    ),
                    model="mock",
                    input_tokens=40,
                    output_tokens=25,
                    cost_usd=0.08,
                )

            async def generate_structured(self, *a: Any, **k: Any) -> Any:
                raise NotImplementedError

        store = HiveStore(hive / "hive.db")
        await store.initialize()
        agent = AgentState(
            agent_id="researcher-test0001",
            name="researcher",
            role="research assistant",
            model="mock-model",
            status=AgentStatus.IDLE,
            workspace=".",
        )
        await store.save_agent(agent)

        daemon = HiveDaemon(hive, heartbeat=0, logs_dir=tmp_path / "logs")
        monkeypatch.setattr("hive.daemon.loop.create_runtime_provider", lambda m: _GoalProvider())

        assert daemon.budget.spent_usd == 0.0
        result = await daemon._run_agent_cycle(agent)
        assert result != "guarded"
        assert daemon.budget.spent_usd == 0.08
        assert daemon.budget.spent_tokens == 65

    @pytest.mark.asyncio
    async def test_custom_strategy_records_spend_without_goal(self, tmp_path: Path) -> None:
        """Custom GoalStrategy spend is metered even when no objective is returned."""
        from hive.agents.goal_strategy import GeneratedGoal, GoalContext

        class _SpendingNullStrategy:
            async def generate_goal(self, context: GoalContext) -> GeneratedGoal:
                return GeneratedGoal(objective=None, cost_usd=0.08, tokens=65)

        cfg = HiveConfig()
        cfg.economy.enabled = False
        cfg.daemon.budget_usd = 0.05
        set_config(cfg)

        hive = tmp_path / ".hive"
        hive.mkdir()
        (hive / "sessions").mkdir()
        (hive / "workspaces").mkdir()
        (hive / "comms").mkdir()
        (hive / "agent_memory").mkdir()
        cfg.save(hive)

        store = HiveStore(hive / "hive.db")
        await store.initialize()
        agent = AgentState(
            agent_id="researcher-test0001",
            name="researcher",
            role="research assistant",
            model="mock-model",
            status=AgentStatus.IDLE,
            workspace=".",
        )
        await store.save_agent(agent)

        daemon = HiveDaemon(
            hive,
            heartbeat=0,
            logs_dir=tmp_path / "logs",
            goal_strategy=_SpendingNullStrategy(),
        )

        assert daemon.budget.spent_usd == 0.0
        result = await daemon._run_agent_cycle(agent)
        assert daemon.budget.spent_usd == 0.08
        assert daemon.budget.spent_tokens == 65
        assert daemon.budget_exceeded is True
        assert result == "guarded"
        assert await store.get_active_goal(agent.agent_id) is None

    @pytest.mark.asyncio
    async def test_timeout_records_generation_spend(self, tmp_path: Path) -> None:
        """Cycle timeout during goal generation still commits reserved spend."""
        from hive.agents.goal_strategy import GeneratedGoal, GoalContext

        class _SlowSpendStrategy:
            async def generate_goal(self, context: GoalContext) -> GeneratedGoal:
                await asyncio.sleep(5)
                return GeneratedGoal(objective=None, cost_usd=0.08, tokens=65)

        cfg = HiveConfig()
        cfg.economy.enabled = False
        cfg.daemon.budget_usd = 10.0
        cfg.daemon.budget_reserve_usd_generation = 0.07
        cfg.daemon.budget_reserve_tokens_generation = 65
        set_config(cfg)

        hive = tmp_path / ".hive"
        hive.mkdir()
        (hive / "sessions").mkdir()
        (hive / "workspaces").mkdir()
        (hive / "comms").mkdir()
        (hive / "agent_memory").mkdir()
        cfg.save(hive)

        store = HiveStore(hive / "hive.db")
        await store.initialize()
        agent = AgentState(
            agent_id="researcher-test0001",
            name="researcher",
            role="research assistant",
            model="mock-model",
            status=AgentStatus.IDLE,
            workspace=".",
        )
        await store.save_agent(agent)

        daemon = HiveDaemon(
            hive,
            heartbeat=0,
            logs_dir=tmp_path / "logs",
            goal_strategy=_SlowSpendStrategy(),
        )

        sem = asyncio.Semaphore(1)
        result = await daemon._run_agent_cycle_guarded(agent, cycle_timeout=1, sem=sem)
        assert result is None
        assert daemon.budget.spent_usd == 0.07
        assert daemon.budget.spent_tokens == 65

    @pytest.mark.asyncio
    async def test_budget_persist_across_daemon_restart(self, tmp_path: Path) -> None:
        """When budget_persist is enabled, spent totals reload on daemon start."""
        cfg = HiveConfig()
        cfg.economy.enabled = False
        cfg.daemon.budget_usd = 5.0
        cfg.daemon.budget_persist = True
        set_config(cfg)

        hive = tmp_path / ".hive"
        hive.mkdir()
        (hive / "sessions").mkdir()
        (hive / "workspaces").mkdir()
        cfg.save(hive)

        daemon = HiveDaemon(hive, heartbeat=0, logs_dir=tmp_path / "logs")
        await daemon.budget.record(cost_usd=1.25, tokens=50)
        daemon.persist_budget()

        daemon2 = HiveDaemon(hive, heartbeat=0, logs_dir=tmp_path / "logs")
        assert daemon2.budget.spent_usd == 1.25
        assert daemon2.budget.spent_tokens == 50

    @pytest.mark.asyncio
    async def test_life_events_stop_after_budget_exceeded(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Subsequent agents must not trigger life-event LLM calls after budget cap."""
        from typing import Any

        from hive.models.base import BaseProvider
        from hive.runtime.types import GenerateResult, Message
        from hive.world.events import Choice, LifeEvent

        cfg = HiveConfig()
        cfg.economy.enabled = True
        cfg.daemon.budget_usd = 0.05
        set_config(cfg)

        hive = tmp_path / ".hive"
        hive.mkdir()
        (hive / "sessions").mkdir()
        (hive / "workspaces").mkdir()
        cfg.save(hive)

        class _CountingProvider(BaseProvider):
            calls = 0

            def __init__(self) -> None:
                super().__init__("mock")

            @property
            def available(self) -> bool:
                return True

            async def generate_with_metadata(self, *a: Any, **k: Any) -> GenerateResult:
                _CountingProvider.calls += 1
                return GenerateResult(
                    message=Message.assistant("1"),
                    model="mock",
                    input_tokens=30,
                    output_tokens=20,
                    cost_usd=0.05,
                )

            async def generate_structured(self, *a: Any, **k: Any) -> Any:
                raise NotImplementedError

        daemon = HiveDaemon(hive, heartbeat=0, logs_dir=tmp_path / "logs")
        assert daemon._event_engine is not None
        await daemon._store.initialize()

        agents = []
        for agent_id, name in (("a1", "ada"), ("a2", "bob")):
            agent = AgentState(
                agent_id=agent_id,
                name=name,
                role="t",
                model="m",
                status=AgentStatus.IDLE,
            )
            await daemon._store.save_agent(agent)
            daemon._identity.load_or_create(agent_id, AgentProfile(name=name, role="t"))
            agents.append(agent)

        event = LifeEvent(
            event_id="loss",
            name="Big Loss",
            description="You lost big.",
            category="financial",
            choices=[Choice(id="accept", description="Accept it")],
        )
        monkeypatch.setattr(
            daemon._event_engine,
            "roll_events",
            lambda aid, c: [event],
        )
        monkeypatch.setattr(
            "hive.daemon.loop.create_runtime_provider",
            lambda m: _CountingProvider(),
        )

        _CountingProvider.calls = 0
        await daemon._process_life_events(agents)

        assert _CountingProvider.calls == 1
        assert daemon.budget_exceeded is True

    @pytest.mark.asyncio
    async def test_life_event_reserves_before_llm(self, tmp_path: Path, monkeypatch) -> None:
        """Life events hold budget capacity via reserve/commit in reserve mode."""
        from typing import Any

        from hive.models.base import BaseProvider
        from hive.runtime.types import GenerateResult, Message
        from hive.world.events import Choice, LifeEvent

        cfg = HiveConfig()
        cfg.economy.enabled = True
        cfg.daemon.budget_usd = 0.05
        cfg.daemon.budget_mode = "reserve"
        cfg.daemon.budget_reserve_usd_generation = 0.05
        set_config(cfg)

        hive = tmp_path / ".hive"
        hive.mkdir()
        (hive / "sessions").mkdir()
        (hive / "workspaces").mkdir()
        cfg.save(hive)

        class _SpendProvider(BaseProvider):
            def __init__(self) -> None:
                super().__init__("mock")

            @property
            def available(self) -> bool:
                return True

            async def generate_with_metadata(self, *a: Any, **k: Any) -> GenerateResult:
                return GenerateResult(
                    message=Message.assistant("1"),
                    model="mock",
                    input_tokens=10,
                    output_tokens=5,
                    cost_usd=0.01,
                )

            async def generate_structured(self, *a: Any, **k: Any) -> Any:
                raise NotImplementedError

        daemon = HiveDaemon(hive, heartbeat=0, logs_dir=tmp_path / "logs")
        assert daemon._event_engine is not None
        await daemon._store.initialize()
        agent = AgentState(agent_id="a1", name="ada", role="t", model="m", status=AgentStatus.IDLE)
        await daemon._store.save_agent(agent)
        daemon._identity.load_or_create("a1", AgentProfile(name="ada", role="t"))

        event = LifeEvent(
            event_id="loss",
            name="Big Loss",
            description="You lost big.",
            category="financial",
            choices=[Choice(id="accept", description="Accept it")],
        )
        monkeypatch.setattr(daemon._event_engine, "roll_events", lambda aid, c: [event])
        monkeypatch.setattr("hive.daemon.loop.create_runtime_provider", lambda m: _SpendProvider())

        # Pre-reserve the full budget so the life-event reserve should fail.
        reservation = await daemon.budget.reserve(0.05, 50)
        assert reservation is not None

        await daemon._process_life_events([agent])

        # Life event LLM should not have run; reservation still held.
        assert daemon.budget.reserved_usd == 0.05
        assert daemon.budget.spent_usd == 0.0


class TestBudgetRestLedgerParity:
    def test_rest_budget_matches_ledger_snapshot(self, tmp_path: Path) -> None:
        """REST /budget and read_budget_snapshot agree after daemon spend + persist."""
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        from hive.daemon.budget import budget_snapshot_to_dict, read_budget_snapshot
        from hive.server.app import create_app

        hive = tmp_path / ".hive"
        hive.mkdir()
        (hive / "sessions").mkdir()
        (hive / "workspaces").mkdir()
        cfg = HiveConfig()
        cfg.daemon.budget_usd = 10.0
        cfg.daemon.budget_tokens = 5000
        cfg.daemon.budget_persist = True
        cfg.save(hive)

        app = create_app(root=tmp_path, with_daemon=True)
        with TestClient(app) as client:
            daemon = app.state.ctx.daemon
            assert daemon is not None
            asyncio.run(daemon.budget.record(cost_usd=1.25, tokens=200))
            daemon.persist_budget()

            rest = client.get("/budget")
            assert rest.status_code == 200
            rest_data = rest.json()
            ledger = budget_snapshot_to_dict(read_budget_snapshot(hive))

            for key in (
                "spent_usd",
                "spent_tokens",
                "budget_usd",
                "budget_tokens",
                "exceeded",
                "unlimited",
            ):
                assert rest_data[key] == ledger[key]
            assert abs(rest_data["remaining_usd"] - ledger["remaining_usd"]) < 0.001
