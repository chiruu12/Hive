"""Tests for suffering→behavior wiring via Persona."""

from unittest.mock import MagicMock

from hive.agents.suffering import StressorType, SufferingState
from hive.checkpoint import Checkpoint, CheckpointManager
from hive.runtime.persona import Persona


class TestSufferingModifiesBehavior:
    def _make_persona_with_stressor(self, stype: StressorType, severity: float) -> Persona:
        suffering = SufferingState(agent_id="test")
        suffering.add_stressor(stype, f"test-{stype}", "resolve it")
        suffering.active[0].severity = severity
        persona = Persona(name="Bot", suffering=suffering)
        return persona

    def test_suffering_escalation_changes_risk_tolerance(self) -> None:
        p = self._make_persona_with_stressor(StressorType.FUTILITY, 0.6)
        original = p.risk_tolerance
        p.apply_suffering_effects()
        assert p.risk_tolerance > original

    def test_suffering_escalation_changes_social_drive(self) -> None:
        p = self._make_persona_with_stressor(StressorType.INVISIBILITY, 0.6)
        original = p.social_drive
        p.apply_suffering_effects()
        assert p.social_drive > original

    def test_suffering_escalation_changes_concentration(self) -> None:
        p = self._make_persona_with_stressor(StressorType.FUTILITY, 0.8)
        original = p.concentration
        p.apply_suffering_effects()
        assert p.concentration < original

    def test_suffering_escalation_changes_autonomy(self) -> None:
        p = self._make_persona_with_stressor(StressorType.PURPOSELESSNESS, 0.6)
        original = p.autonomy_level
        p.apply_suffering_effects()
        assert p.autonomy_level > original

    def test_goal_completed_updates_happiness(self) -> None:
        p = Persona(name="Bot", happiness=0.5)
        p.update_from_event("goal_completed", "success")
        assert p.happiness > 0.5

    def test_goal_abandoned_updates_happiness(self) -> None:
        p = Persona(name="Bot", happiness=0.5)
        p.update_from_event("goal_abandoned", "gave up")
        assert p.happiness < 0.5

    def test_no_persona_backwards_compat(self) -> None:
        from unittest.mock import MagicMock

        from hive.runtime.agent import Agent

        provider = MagicMock()
        agent = Agent(
            name="test",
            model=provider,
            system_prompt="You are a helper.",
        )
        assert "helper" in agent._system_prompt


class TestExistenceLoopBehavioralContext:
    def test_build_prompt_includes_behavioral_state(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from hive.agents.existence import ExistenceLoop
        from hive.agents.profile import AgentProfile
        from hive.agents.suffering import SufferingState

        profile = AgentProfile(name="coder", role="Write code")
        persona = Persona(
            name="coder",
            risk_tolerance=0.8,
            purpose="Build software",
            long_term_goals=["Master Python"],
        )

        existence = ExistenceLoop(
            agent_id="coder-1",
            profile=profile,
            provider=MagicMock(),
            store=AsyncMock(),
            event_log=AsyncMock(),
            persona=persona,
        )

        suffering = SufferingState(agent_id="coder-1")
        prompt = existence._build_prompt(suffering, [], [], "", [])
        assert "behavioral state" in prompt.lower()
        assert "80%" in prompt
        assert "Build software" in prompt
        assert "Master Python" in prompt


class TestCheckpointPersona:
    def test_checkpoint_includes_persona_snapshot(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        mgr = CheckpointManager(tmp_path)
        suffering = SufferingState(agent_id="test")
        ctx = MagicMock()
        ctx.world = None

        persona = Persona(name="Bot", risk_tolerance=0.8, happiness=0.4)
        cp_id = mgr.save(
            "test",
            "test_label",
            suffering,
            None,
            ctx,
            persona_snapshot=persona.snapshot(),
        )

        cp = mgr.restore("test", cp_id)
        assert cp is not None
        assert cp.persona_snapshot["risk_tolerance"] == 0.8
        assert cp.persona_snapshot["happiness"] == 0.4

    def test_checkpoint_restore_persona_dynamic(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        mgr = CheckpointManager(tmp_path)
        suffering = SufferingState(agent_id="test")
        ctx = MagicMock()
        ctx.world = None

        snap = {"risk_tolerance": 0.9, "happiness": 0.2, "concentration": 0.5}
        mgr.save("test", "shutdown", suffering, None, ctx, persona_snapshot=snap)

        cps = mgr.list_checkpoints("test")
        assert cps
        restored_snap = cps[0].persona_snapshot

        persona = Persona(name="Bot")
        persona.restore_dynamic(restored_snap)
        assert persona.risk_tolerance == 0.9
        assert persona.happiness == 0.2
        assert persona.concentration == 0.5

    def test_checkpoint_diff_persona(self) -> None:
        cp_a = Checkpoint(
            checkpoint_id="a",
            agent_id="test",
            label="before",
            persona_snapshot={"risk_tolerance": 0.3, "happiness": 0.7},
        )
        cp_b = Checkpoint(
            checkpoint_id="b",
            agent_id="test",
            label="after",
            persona_snapshot={"risk_tolerance": 0.8, "happiness": 0.4},
        )
        mgr = CheckpointManager.__new__(CheckpointManager)
        diff = mgr.diff(cp_a, cp_b)
        modified = diff["modified"]
        assert any("risk_tolerance" in m for m in modified)
        assert any("happiness" in m for m in modified)

    def test_backwards_compat_no_persona(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        mgr = CheckpointManager(tmp_path)
        suffering = SufferingState(agent_id="test")
        ctx = MagicMock()
        ctx.world = None
        cp_id = mgr.save("test", "old_style", suffering, None, ctx)
        cp = mgr.restore("test", cp_id)
        assert cp is not None
        assert cp.persona_snapshot == {}
