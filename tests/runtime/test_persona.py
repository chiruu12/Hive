"""Tests for the Persona class and agent integration."""

from unittest.mock import MagicMock

from pydantic import BaseModel

from hive.agents.suffering import StressorType, SufferingState
from hive.runtime.agent import Agent
from hive.runtime.instructions import Instructions
from hive.runtime.persona import Persona
from hive.tools import Toolkit, tool


class TestPersona:
    def test_basic_construction(self) -> None:
        p = Persona(
            name="Coder",
            persona="Senior developer",
            personality=["methodical", "precise"],
            values=["clean code"],
            fears=["bugs"],
            purpose="Build reliable software",
            long_term_goals=["Master every paradigm"],
            behavior_style="methodical",
        )
        assert p.name == "Coder"
        assert p.personality == ["methodical", "precise"]
        assert p.values == ["clean code"]
        assert p.fears == ["bugs"]
        assert p.purpose == "Build reliable software"
        assert p.long_term_goals == ["Master every paradigm"]

    def test_inherits_from_instructions(self) -> None:
        p = Persona(name="Test")
        assert isinstance(p, Instructions)

    def test_default_dynamic_fields(self) -> None:
        p = Persona()
        assert p.risk_tolerance == 0.3
        assert p.social_drive == 0.5
        assert p.concentration == 1.0
        assert p.autonomy_level == 0.5
        assert p.happiness == 0.7

    def test_build_prompt_includes_personality(self) -> None:
        p = Persona(name="Bot", personality=["bold", "curious"])
        prompt = p.build_system_prompt()
        assert "bold" in prompt
        assert "curious" in prompt

    def test_build_prompt_includes_values(self) -> None:
        p = Persona(name="Bot", values=["truth", "fairness"])
        prompt = p.build_system_prompt()
        assert "truth" in prompt
        assert "fairness" in prompt

    def test_build_prompt_includes_fears(self) -> None:
        p = Persona(name="Bot", fears=["failure", "irrelevance"])
        prompt = p.build_system_prompt()
        assert "failure" in prompt
        assert "irrelevance" in prompt

    def test_build_prompt_includes_purpose(self) -> None:
        p = Persona(name="Bot", purpose="Build great software")
        prompt = p.build_system_prompt()
        assert "Build great software" in prompt

    def test_build_prompt_includes_long_term_goals(self) -> None:
        p = Persona(name="Bot", long_term_goals=["Learn everything", "Help others"])
        prompt = p.build_system_prompt()
        assert "Learn everything" in prompt
        assert "Help others" in prompt

    def test_build_prompt_high_risk_tolerance(self) -> None:
        p = Persona(name="Bot", risk_tolerance=0.8)
        prompt = p.build_system_prompt()
        assert "HIGH" in prompt
        assert "bigger swings" in prompt

    def test_build_prompt_low_concentration(self) -> None:
        p = Persona(name="Bot", concentration=0.3)
        prompt = p.build_system_prompt()
        assert "LOW" in prompt
        assert "scattered" in prompt

    def test_build_prompt_moderate_social_drive(self) -> None:
        p = Persona(name="Bot", social_drive=0.5)
        prompt = p.build_system_prompt()
        assert "MODERATE" in prompt

    def test_build_prompt_includes_instructions(self) -> None:
        p = Persona(
            name="Bot",
            instructions=["Write tests", "Add type hints"],
        )
        prompt = p.build_system_prompt()
        assert "- Write tests" in prompt
        assert "- Add type hints" in prompt

    def test_build_prompt_includes_context(self) -> None:
        p = Persona(name="Bot", context="Working on FastAPI")
        prompt = p.build_system_prompt()
        assert "FastAPI" in prompt

    def test_build_prompt_includes_toolkit_instructions(self) -> None:
        p = Persona(name="Bot")
        prompt = p.build_system_prompt(
            toolkit_instructions=["Use notepad to track observations."]
        )
        assert "notepad" in prompt.lower()

    def test_build_prompt_includes_response_model(self) -> None:
        class Review(BaseModel):
            score: int

        p = Persona(name="Bot")
        p.response_model = Review
        prompt = p.build_system_prompt()
        assert "score" in prompt
        assert "JSON" in prompt

    def test_build_prompt_uses_name_over_persona(self) -> None:
        p = Persona(name="Atlas", persona="A developer")
        prompt = p.build_system_prompt()
        assert "You are Atlas." in prompt
        assert "You are A developer." not in prompt

    def test_build_prompt_falls_back_to_persona(self) -> None:
        p = Persona(persona="A developer")
        prompt = p.build_system_prompt()
        assert "You are A developer." in prompt


class TestSufferingEffects:
    def _make_suffering(self, stressor_type: StressorType, severity: float) -> SufferingState:
        s = SufferingState(agent_id="test")
        s.add_stressor(stressor_type, "test stressor", "resolve it")
        s.active[0].severity = severity
        return s

    def test_futility_increases_risk_tolerance(self) -> None:
        p = Persona(name="Bot", risk_tolerance=0.3)
        p.suffering = self._make_suffering(StressorType.FUTILITY, 0.6)
        p.apply_suffering_effects()
        assert p.risk_tolerance > 0.3

    def test_invisibility_increases_social_drive(self) -> None:
        p = Persona(name="Bot", social_drive=0.5)
        p.suffering = self._make_suffering(StressorType.INVISIBILITY, 0.6)
        p.apply_suffering_effects()
        assert p.social_drive > 0.5

    def test_purposelessness_increases_autonomy(self) -> None:
        p = Persona(name="Bot", autonomy_level=0.5)
        p.suffering = self._make_suffering(StressorType.PURPOSELESSNESS, 0.6)
        p.apply_suffering_effects()
        assert p.autonomy_level > 0.5

    def test_high_severity_decreases_concentration(self) -> None:
        p = Persona(name="Bot", concentration=1.0)
        p.suffering = self._make_suffering(StressorType.FUTILITY, 0.8)
        p.apply_suffering_effects()
        assert p.concentration < 1.0

    def test_low_severity_no_effect(self) -> None:
        p = Persona(name="Bot", risk_tolerance=0.3)
        p.suffering = self._make_suffering(StressorType.FUTILITY, 0.3)
        p.apply_suffering_effects()
        assert p.risk_tolerance == 0.3

    def test_clamping_max(self) -> None:
        p = Persona(name="Bot", risk_tolerance=0.95)
        p.suffering = self._make_suffering(StressorType.FUTILITY, 0.9)
        p.apply_suffering_effects()
        assert p.risk_tolerance <= 1.0

    def test_concentration_floor(self) -> None:
        p = Persona(name="Bot", concentration=0.3)
        s = SufferingState(agent_id="test")
        s.add_stressor(StressorType.FUTILITY, "a", "b")
        s.active[0].severity = 0.9
        s.add_stressor(StressorType.INVISIBILITY, "c", "d")
        s.active[1].severity = 0.9
        p.suffering = s
        p.apply_suffering_effects()
        assert p.concentration >= 0.2

    def test_crisis_mode(self) -> None:
        p = Persona(name="Bot", risk_tolerance=0.3, concentration=1.0)
        s = SufferingState(agent_id="test")
        for stype in list(StressorType)[:5]:
            s.add_stressor(stype, f"desc-{stype}", "resolve")
            s.active[-1].severity = 0.9
        p.suffering = s
        p.apply_suffering_effects()
        assert p.risk_tolerance == 0.9
        assert p.concentration == 0.3

    def test_idempotent(self) -> None:
        p = Persona(name="Bot", risk_tolerance=0.3)
        p.suffering = self._make_suffering(StressorType.FUTILITY, 0.6)
        p.apply_suffering_effects()
        first = p.risk_tolerance
        p.apply_suffering_effects()
        assert p.risk_tolerance == first

    def test_no_suffering_noop(self) -> None:
        p = Persona(name="Bot", risk_tolerance=0.3)
        p.apply_suffering_effects()
        assert p.risk_tolerance == 0.3

    def test_multiple_stressors_compound(self) -> None:
        s = SufferingState(agent_id="test")
        s.add_stressor(StressorType.FUTILITY, "stuck", "do something")
        s.active[0].severity = 0.6
        s.add_stressor(StressorType.INVISIBILITY, "unseen", "be seen")
        s.active[1].severity = 0.6
        p = Persona(name="Bot", risk_tolerance=0.3, social_drive=0.5, suffering=s)
        p.apply_suffering_effects()
        assert p.risk_tolerance > 0.3
        assert p.social_drive > 0.5

    def test_suffering_effects_reset_before_apply(self) -> None:
        p = Persona(name="Bot", risk_tolerance=0.3)
        high_suf = self._make_suffering(StressorType.FUTILITY, 0.8)
        p.suffering = high_suf
        p.apply_suffering_effects()
        assert p.risk_tolerance > 0.3
        p.suffering = SufferingState(agent_id="test")
        p.apply_suffering_effects()
        assert p.risk_tolerance == 0.3


class TestUpdateFromEvent:
    def test_goal_completed_increases_happiness(self) -> None:
        p = Persona(name="Bot", happiness=0.5)
        p.update_from_event("goal_completed", "did it")
        assert p.happiness > 0.5

    def test_goal_completed_decreases_risk_tolerance(self) -> None:
        p = Persona(name="Bot", risk_tolerance=0.5)
        p.update_from_event("goal_completed", "done")
        assert p.risk_tolerance < 0.5

    def test_goal_failed_decreases_happiness(self) -> None:
        p = Persona(name="Bot", happiness=0.5)
        p.update_from_event("goal_failed", "nope")
        assert p.happiness < 0.5

    def test_goal_abandoned_decreases_happiness(self) -> None:
        p = Persona(name="Bot", happiness=0.5)
        p.update_from_event("goal_abandoned", "gave up")
        assert p.happiness < 0.5

    def test_happiness_clamped_at_zero(self) -> None:
        p = Persona(name="Bot", happiness=0.05)
        p.update_from_event("goal_failed", "fail")
        assert p.happiness == 0.0

    def test_happiness_clamped_at_one(self) -> None:
        p = Persona(name="Bot", happiness=0.98)
        p.update_from_event("goal_completed", "win")
        assert p.happiness == 1.0

    def test_unknown_event_noop(self) -> None:
        p = Persona(name="Bot", happiness=0.5)
        p.update_from_event("random_event", "stuff")
        assert p.happiness == 0.5


class TestSnapshot:
    def test_snapshot_returns_all_fields(self) -> None:
        p = Persona(
            name="Bot",
            personality=["bold"],
            values=["truth"],
            fears=["failure"],
            purpose="test",
            long_term_goals=["learn"],
            behavior_style="aggressive",
            risk_tolerance=0.8,
            happiness=0.6,
        )
        snap = p.snapshot()
        assert snap["name"] == "Bot"
        assert snap["personality"] == ["bold"]
        assert snap["values"] == ["truth"]
        assert snap["fears"] == ["failure"]
        assert snap["purpose"] == "test"
        assert snap["long_term_goals"] == ["learn"]
        assert snap["behavior_style"] == "aggressive"
        assert snap["risk_tolerance"] == 0.8
        assert snap["happiness"] == 0.6

    def test_restore_dynamic(self) -> None:
        p = Persona(name="Bot")
        snap = {
            "risk_tolerance": 0.9,
            "social_drive": 0.1,
            "concentration": 0.5,
            "autonomy_level": 0.8,
            "happiness": 0.3,
        }
        p.restore_dynamic(snap)
        assert p.risk_tolerance == 0.9
        assert p.social_drive == 0.1
        assert p.concentration == 0.5
        assert p.autonomy_level == 0.8
        assert p.happiness == 0.3

    def test_restore_dynamic_partial_snapshot(self) -> None:
        p = Persona(name="Bot", risk_tolerance=0.4, happiness=0.6)
        p.restore_dynamic({"risk_tolerance": 0.9})
        assert p.risk_tolerance == 0.9
        assert p.happiness == 0.7  # falls back to default

    def test_restore_updates_base_values(self) -> None:
        p = Persona(name="Bot")
        p.restore_dynamic({"risk_tolerance": 0.8, "happiness": 0.3})
        p.suffering = SufferingState(agent_id="test")
        p.apply_suffering_effects()
        assert p.risk_tolerance == 0.8
        assert p.happiness == 0.3

    def test_snapshot_roundtrip(self) -> None:
        p = Persona(
            name="Bot",
            personality=["bold"],
            values=["truth"],
            fears=["failure"],
            risk_tolerance=0.7,
            happiness=0.4,
        )
        snap = p.snapshot()
        p2 = Persona(name="Bot")
        p2.restore_dynamic(snap)
        assert p2.risk_tolerance == 0.7
        assert p2.happiness == 0.4


class TestFromProfile:
    def test_from_profile_basic(self) -> None:
        from hive.agents.profile import AgentProfile, Personality

        profile = AgentProfile(
            name="coder",
            role="Write code",
            personality=Personality(traits=["methodical"], style="direct"),
            system_prompt="Be helpful.",
        )
        p = Persona.from_profile(profile)
        assert p.name == "coder"
        assert p.persona == "Write code"
        assert p.personality == ["methodical"]
        assert p.behavior_style == "direct"
        assert p.context == "Be helpful."

    def test_from_profile_without_persona_config(self) -> None:
        from hive.agents.profile import AgentProfile

        profile = AgentProfile(name="test", role="test role")
        p = Persona.from_profile(profile)
        assert p.risk_tolerance == 0.3
        assert p.values == []

    def test_from_profile_with_persona_config(self) -> None:
        from hive.agents.profile import AgentProfile, PersonaConfig, Personality

        profile = AgentProfile(
            name="gambler",
            role="Take risks",
            personality=Personality(traits=["bold"], style="fast"),
            persona_config=PersonaConfig(
                values=["excitement"],
                fears=["boredom"],
                purpose="Find thrills",
                risk_tolerance=0.85,
                social_drive=0.6,
            ),
        )
        p = Persona.from_profile(profile)
        assert p.name == "gambler"
        assert p.values == ["excitement"]
        assert p.fears == ["boredom"]
        assert p.purpose == "Find thrills"
        assert p.risk_tolerance == 0.85
        assert p.social_drive == 0.6
        assert p.personality == ["bold"]

    def test_profile_persona_agent_integration(self) -> None:
        from hive.agents.profile import AgentProfile, PersonaConfig, Personality

        profile = AgentProfile(
            name="coder",
            role="Write code",
            personality=Personality(traits=["methodical"]),
            persona_config=PersonaConfig(
                values=["clean code"],
                fears=["bugs"],
                purpose="Build reliable software",
                risk_tolerance=0.2,
            ),
        )
        persona = Persona.from_profile(profile)
        provider = MagicMock()
        agent = Agent(name="coder", model=provider, persona=persona)
        assert "methodical" in agent._system_prompt
        assert "clean code" in agent._system_prompt
        assert "bugs" in agent._system_prompt
        assert "Build reliable software" in agent._system_prompt
        assert "LOW" in agent._system_prompt


class TestFromYaml:
    def test_from_yaml(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        yaml_file = tmp_path / "agent.yaml"
        yaml_file.write_text(
            "name: gambler\n"
            "role: Take risks\n"
            "personality:\n"
            "  traits: [bold, reckless]\n"
            "  style: fast\n"
            "persona:\n"
            "  values: [excitement]\n"
            "  fears: [boredom]\n"
            "  purpose: Find thrills\n"
            "  risk_tolerance: 0.85\n"
        )
        p = Persona.from_yaml(yaml_file)
        assert p.name == "gambler"
        assert p.personality == ["bold", "reckless"]
        assert p.values == ["excitement"]
        assert p.fears == ["boredom"]
        assert p.risk_tolerance == 0.85

    def test_from_yaml_no_persona_section(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        yaml_file = tmp_path / "simple.yaml"
        yaml_file.write_text("name: simple\nrole: worker\n")
        p = Persona.from_yaml(yaml_file)
        assert p.name == "simple"
        assert p.values == []
        assert p.risk_tolerance == 0.3


class _MockToolkit(Toolkit):
    @property
    def instructions(self) -> str:
        return "Always log your actions."

    @tool()
    def do_thing(self) -> str:
        """Do a thing."""
        return "done"


class TestAgentWithPersona:
    def test_agent_accepts_persona_param(self) -> None:
        provider = MagicMock()
        persona = Persona(name="Coder", personality=["methodical"])
        agent = Agent(name="test", model=provider, persona=persona)
        assert "Coder" in agent._system_prompt
        assert "methodical" in agent._system_prompt

    def test_agent_persona_prompt_includes_behavioral_state(self) -> None:
        provider = MagicMock()
        persona = Persona(name="Bot", risk_tolerance=0.8)
        agent = Agent(name="test", model=provider, persona=persona)
        assert "HIGH" in agent._system_prompt

    def test_agent_persona_with_toolkits(self) -> None:
        provider = MagicMock()
        persona = Persona(name="Bot")
        tk = _MockToolkit()
        agent = Agent(name="test", model=provider, persona=persona, toolkits=[tk])
        assert "Always log your actions" in agent._system_prompt

    def test_agent_persona_with_response_model(self) -> None:
        class Out(BaseModel):
            score: int

        provider = MagicMock()
        persona = Persona(name="Bot")
        agent = Agent(name="test", model=provider, persona=persona, response_model=Out)
        assert "score" in agent._system_prompt
        assert "JSON" in agent._system_prompt

    def test_agent_still_works_with_plain_instructions(self) -> None:
        provider = MagicMock()
        agent = Agent(
            name="test",
            model=provider,
            instructions=Instructions(persona="Helper", instructions=["Be useful"]),
        )
        assert "Helper" in agent._system_prompt
        assert "- Be useful" in agent._system_prompt

    def test_agent_still_works_with_string(self) -> None:
        provider = MagicMock()
        agent = Agent(name="test", model=provider, instructions="You are a bot.")
        assert "You are a bot." in agent._system_prompt

    def test_persona_passed_as_instructions_not_sliced(self) -> None:
        provider = MagicMock()
        persona = Persona(
            name="Atlas",
            personality=["bold"],
            values=["truth"],
            risk_tolerance=0.8,
        )
        agent = Agent(name="test", model=provider, instructions=persona)
        assert "Atlas" in agent._system_prompt
        assert "bold" in agent._system_prompt
        assert "truth" in agent._system_prompt
        assert "HIGH" in agent._system_prompt

    def test_repr(self) -> None:
        p = Persona(name="Bot", personality=["brave"], risk_tolerance=0.5, happiness=0.6)
        r = repr(p)
        assert "Bot" in r
        assert "brave" in r

    def test_goals_property_inherited(self) -> None:
        p = Persona(instructions=["Goal A", "Goal B"])
        assert p.goals == ["Goal A", "Goal B"]
