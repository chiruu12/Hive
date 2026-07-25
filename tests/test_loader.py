"""Tests for YAMLScenario loader."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hive.interactions.base import AgentSlot, ScenarioResult
from hive.interactions.loader import YAMLScenario, load_scenario


def _write_scenario(tmp_path: Path, config: dict) -> Path:
    path = tmp_path / "scenario.yaml"
    path.write_text(yaml.dump(config))
    return path


@pytest.fixture
def detective_config() -> dict:
    return {
        "name": "Murder Mystery",
        "pattern": "round_table",
        "num_rounds": 3,
        "context": "A murder occurred at the mansion.",
        "agents": [
            {
                "id": "detective",
                "name": "Detective",
                "model": "claude-haiku-4-5",
                "persona": "Brilliant investigator",
                "role": "lead detective",
                "secret": "I saw the butler flee",
                "memory": "full",
            },
            {
                "id": "butler",
                "name": "Butler",
                "model": "gpt-4o-mini",
                "persona": "Nervous servant",
                "role": "suspect",
            },
        ],
        "evidence": [
            {"round": 0, "reveal": "A bloody glove was found."},
            {"round": 2, "reveal": "Security footage shows the butler."},
        ],
        "scoring": {"correct_accusation": 10, "wrong_accusation": -5},
        "final_phase": "accusation",
        "correct_answer": "butler",
    }


class TestYAMLScenario:
    def test_load_basic(self, tmp_path: Path, detective_config: dict):
        path = _write_scenario(tmp_path, detective_config)
        scenario = YAMLScenario(path)

        assert scenario.name == "Murder Mystery"
        assert scenario.pattern_type == "round_table"
        assert scenario.num_rounds == 3

    def test_load_defaults(self, tmp_path: Path):
        path = _write_scenario(tmp_path, {})
        scenario = YAMLScenario(path)

        assert scenario.name == path.stem
        assert scenario.pattern_type == "round_table"
        assert scenario.num_rounds == 4

    def test_setup_creates_agent_slots(self, tmp_path: Path, detective_config: dict):
        path = _write_scenario(tmp_path, detective_config)
        scenario = YAMLScenario(path)
        agents = scenario.setup()

        assert len(agents) == 2
        assert isinstance(agents[0], AgentSlot)
        assert agents[0].slot_id == "detective"
        assert agents[0].name == "Detective"
        assert agents[0].model == "claude-haiku-4-5"
        assert agents[0].persona == "Brilliant investigator"
        assert agents[0].role == "lead detective"
        assert agents[0].secret == "I saw the butler flee"
        assert agents[0].memory_type == "full"

    def test_setup_agent_defaults(self, tmp_path: Path):
        path = _write_scenario(tmp_path, {"agents": [{}]})
        scenario = YAMLScenario(path)
        agents = scenario.setup()

        assert agents[0].slot_id == "agent_0"
        assert agents[0].name == "Agent 0"
        assert agents[0].model == "claude-haiku-4-5"

    def test_system_prompt_includes_secret(self, tmp_path: Path, detective_config: dict):
        path = _write_scenario(tmp_path, detective_config)
        scenario = YAMLScenario(path)
        agents = scenario.setup()

        assert "SECRET" in agents[0].system_prompt
        assert "I saw the butler flee" in agents[0].system_prompt

    def test_system_prompt_includes_context(self, tmp_path: Path, detective_config: dict):
        path = _write_scenario(tmp_path, detective_config)
        scenario = YAMLScenario(path)
        agents = scenario.setup()

        assert "A murder occurred at the mansion." in agents[0].system_prompt

    def test_system_prompt_no_secret(self, tmp_path: Path, detective_config: dict):
        path = _write_scenario(tmp_path, detective_config)
        scenario = YAMLScenario(path)
        agents = scenario.setup()

        # Butler has no secret
        assert "SECRET" not in agents[1].system_prompt

    def test_build_round_prompt(self, tmp_path: Path, detective_config: dict):
        path = _write_scenario(tmp_path, detective_config)
        scenario = YAMLScenario(path)
        agents = scenario.setup()

        prompt = scenario.build_round_prompt(agents[0], 1, "Previous messages here")
        assert "Round 2 of 3" in prompt
        assert "Previous messages here" in prompt

    def test_get_evidence(self, tmp_path: Path, detective_config: dict):
        path = _write_scenario(tmp_path, detective_config)
        scenario = YAMLScenario(path)

        assert scenario.get_evidence(0) == "A bloody glove was found."
        assert scenario.get_evidence(2) == "Security footage shows the butler."
        assert scenario.get_evidence(1) == ""

    def test_get_final_prompt_accusation(self, tmp_path: Path, detective_config: dict):
        path = _write_scenario(tmp_path, detective_config)
        scenario = YAMLScenario(path)
        agents = scenario.setup()

        prompt = scenario.get_final_prompt(agents[0], "Discussion summary")
        assert "accusation" in prompt.lower()
        assert "Discussion summary" in prompt
        assert "accused" in prompt

    def test_get_final_prompt_vote(self, tmp_path: Path):
        config = {"final_phase": "vote", "agents": [{"id": "a"}]}
        path = _write_scenario(tmp_path, config)
        scenario = YAMLScenario(path)
        agents = scenario.setup()

        prompt = scenario.get_final_prompt(agents[0], "context")
        assert "vote" in prompt.lower()
        assert "vote" in prompt

    def test_get_final_prompt_custom(self, tmp_path: Path):
        config = {"final_phase": "verdict", "agents": [{"id": "a"}]}
        path = _write_scenario(tmp_path, config)
        scenario = YAMLScenario(path)
        agents = scenario.setup()

        prompt = scenario.get_final_prompt(agents[0], "ctx")
        assert "verdict" in prompt

    def test_get_final_prompt_none(self, tmp_path: Path):
        config = {"agents": [{"id": "a"}]}
        path = _write_scenario(tmp_path, config)
        scenario = YAMLScenario(path)
        agents = scenario.setup()

        assert scenario.get_final_prompt(agents[0], "ctx") == ""

    def test_evaluate_correct_accusation(self, tmp_path: Path, detective_config: dict):
        path = _write_scenario(tmp_path, detective_config)
        scenario = YAMLScenario(path)

        result = ScenarioResult(
            name="Murder Mystery",
            final_actions={"detective": '{"accused": "butler", "reason": "saw him"}'},
        )
        scores = scenario.evaluate(result)
        assert scores["detective"] == 10

    def test_evaluate_wrong_accusation(self, tmp_path: Path, detective_config: dict):
        path = _write_scenario(tmp_path, detective_config)
        scenario = YAMLScenario(path)

        result = ScenarioResult(
            name="Murder Mystery",
            final_actions={"detective": '{"accused": "maid", "reason": "suspicious"}'},
        )
        scores = scenario.evaluate(result)
        assert scores["detective"] == -5

    def test_evaluate_malformed_json(self, tmp_path: Path, detective_config: dict):
        path = _write_scenario(tmp_path, detective_config)
        scenario = YAMLScenario(path)

        result = ScenarioResult(
            name="Murder Mystery",
            final_actions={"detective": "I think it was the butler!"},
        )
        scores = scenario.evaluate(result)
        assert scores["detective"] == -5

    def test_evaluate_no_correct_answer(self, tmp_path: Path):
        config = {"agents": [{"id": "a"}]}
        path = _write_scenario(tmp_path, config)
        scenario = YAMLScenario(path)

        result = ScenarioResult(name="test", final_actions={"a": "something"})
        assert scenario.evaluate(result) == {}

    def test_evaluate_alternative_json_field(self, tmp_path: Path, detective_config: dict):
        """evaluate() also checks 'killer' field as fallback."""
        path = _write_scenario(tmp_path, detective_config)
        scenario = YAMLScenario(path)

        result = ScenarioResult(
            name="Murder Mystery",
            final_actions={"detective": '{"killer": "Butler", "reason": "motive"}'},
        )
        scores = scenario.evaluate(result)
        assert scores["detective"] == 10


class TestLoadScenario:
    def test_load_scenario_function(self, tmp_path: Path):
        path = _write_scenario(tmp_path, {"name": "Test", "agents": []})
        scenario = load_scenario(path)
        assert isinstance(scenario, YAMLScenario)
        assert scenario.name == "Test"
