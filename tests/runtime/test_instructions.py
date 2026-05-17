"""Tests for the Instructions class and agent integration."""

from unittest.mock import MagicMock

from pydantic import BaseModel

from hive.runtime.agent import Agent
from hive.runtime.instructions import Instructions
from hive.tools import Toolkit, tool


class TestInstructions:
    def test_persona_only(self):
        instr = Instructions(persona="A helpful assistant")
        prompt = instr.build_system_prompt()
        assert "You are A helpful assistant." in prompt

    def test_instructions_as_string(self):
        instr = Instructions(instructions="Follow PEP 8")
        prompt = instr.build_system_prompt()
        assert "- Follow PEP 8" in prompt

    def test_instructions_as_list(self):
        instr = Instructions(instructions=["Write tests", "Add type hints"])
        prompt = instr.build_system_prompt()
        assert "- Write tests" in prompt
        assert "- Add type hints" in prompt

    def test_context(self):
        instr = Instructions(
            persona="Developer",
            context="FastAPI backend with PostgreSQL",
        )
        prompt = instr.build_system_prompt()
        assert "FastAPI backend" in prompt

    def test_full_configuration(self):
        instr = Instructions(
            persona="Senior Python developer",
            instructions=["Write clean code", "Add docstrings"],
            context="Working on an API server",
        )
        prompt = instr.build_system_prompt()
        assert "Senior Python developer" in prompt
        assert "- Write clean code" in prompt
        assert "- Add docstrings" in prompt
        assert "API server" in prompt

    def test_response_model_via_setter(self):
        class Review(BaseModel):
            score: int
            summary: str

        instr = Instructions(persona="Code reviewer")
        instr.response_model = Review
        prompt = instr.build_system_prompt()
        assert "JSON" in prompt
        assert "score" in prompt
        assert "summary" in prompt

    def test_toolkit_instructions_appended(self):
        instr = Instructions(persona="Helper")
        prompt = instr.build_system_prompt(
            toolkit_instructions=["Use the notepad to track observations."]
        )
        assert "notepad" in prompt.lower()

    def test_empty_instructions(self):
        instr = Instructions()
        prompt = instr.build_system_prompt()
        assert prompt == ""

    def test_goals_property(self):
        instr = Instructions(instructions=["Goal A", "Goal B"])
        assert instr.goals == ["Goal A", "Goal B"]

    def test_repr(self):
        instr = Instructions(persona="Dev", instructions=["Code"])
        r = repr(instr)
        assert "Dev" in r
        assert "Code" in r


class _MockToolkit(Toolkit):
    @property
    def instructions(self) -> str:
        return "Always log your actions."

    @tool()
    def do_thing(self) -> str:
        """Do a thing."""
        return "done"


class TestAgentWithInstructions:
    def test_agent_accepts_instructions_object(self):
        provider = MagicMock()
        agent = Agent(
            name="test",
            model=provider,
            instructions=Instructions(
                persona="Test agent",
                instructions=["Be helpful"],
            ),
        )
        assert "Test agent" in agent._system_prompt
        assert "- Be helpful" in agent._system_prompt

    def test_agent_accepts_string(self):
        provider = MagicMock()
        agent = Agent(
            name="test",
            model=provider,
            instructions="You are a helpful assistant.",
        )
        assert agent._system_prompt == "You are a helpful assistant."

    def test_agent_falls_back_to_system_prompt(self):
        provider = MagicMock()
        agent = Agent(
            name="test",
            model=provider,
            system_prompt="Legacy prompt",
        )
        assert agent._system_prompt == "Legacy prompt"

    def test_agent_collects_toolkit_instructions(self):
        provider = MagicMock()
        tk = _MockToolkit()
        agent = Agent(
            name="test",
            model=provider,
            instructions=Instructions(persona="Worker"),
            toolkits=[tk],
        )
        assert "Always log your actions" in agent._system_prompt

    def test_toolkit_instructions_not_added_with_plain_string(self):
        provider = MagicMock()
        tk = _MockToolkit()
        agent = Agent(
            name="test",
            model=provider,
            instructions="Simple prompt",
            toolkits=[tk],
        )
        assert agent._system_prompt == "Simple prompt"

    def test_agent_passes_response_model_to_instructions(self):
        class Output(BaseModel):
            answer: str

        provider = MagicMock()
        agent = Agent(
            name="test",
            model=provider,
            instructions=Instructions(persona="Helper"),
            response_model=Output,
        )
        assert "answer" in agent._system_prompt
        assert "JSON" in agent._system_prompt
