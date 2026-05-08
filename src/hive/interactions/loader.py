"""Scenario loader — load scenarios from YAML config files."""

import json
from pathlib import Path

import yaml

from hive.interactions.base import AgentSlot, Scenario, ScenarioResult


class YAMLScenario(Scenario):
    """A scenario loaded from a YAML config file."""

    def __init__(self, config_path: Path):
        with open(config_path) as f:
            self._config = yaml.safe_load(f)
        self.name = self._config.get("name", config_path.stem)
        self.pattern_type = self._config.get("pattern", "round_table")
        self.num_rounds = self._config.get("num_rounds", 4)
        self._agents_config = self._config.get("agents", [])
        self._evidence = {e["round"]: e["reveal"] for e in self._config.get("evidence", [])}
        self._scoring = self._config.get("scoring", {})
        self._context = self._config.get("context", "")

    def setup(self) -> list[AgentSlot]:
        agents = []
        for i, cfg in enumerate(self._agents_config):
            slot = AgentSlot(
                slot_id=cfg.get("id", f"agent_{i}"),
                name=cfg.get("name", f"Agent {i}"),
                model=cfg.get("model", "claude-haiku-4-5"),
                persona=cfg.get("persona", ""),
                role=cfg.get("role", ""),
                secret=cfg.get("secret", ""),
                memory_type=cfg.get("memory", "selective"),
                system_prompt=self._build_system_prompt(cfg),
            )
            agents.append(slot)
        return agents

    def _build_system_prompt(self, cfg: dict) -> str:
        parts = [
            f"You are {cfg.get('name', 'an agent')}.",
            f"Role: {cfg.get('role', 'participant')}.",
            f"Personality: {cfg.get('persona', '')}.",
        ]
        if cfg.get("secret"):
            parts.append(f"\nSECRET (only you know this): {cfg['secret']}")
        if self._context:
            parts.append(f"\nContext: {self._context}")
        parts.append("\nStay in character. Be concise. Never break character.")
        return "\n".join(parts)

    def build_round_prompt(self, agent: AgentSlot, round_num: int, memory_context: str) -> str:
        return (
            f"Round {round_num + 1} of {self.num_rounds}.\n\n"
            f"Conversation so far:\n{memory_context}\n\n"
            "What do you say? Respond in character, 1-3 sentences."
        )

    def get_evidence(self, round_num: int) -> str:
        return self._evidence.get(round_num, "")

    def get_final_prompt(self, agent: AgentSlot, memory_context: str) -> str:
        final_phase = self._config.get("final_phase")
        if not final_phase:
            return ""
        if final_phase == "accusation":
            return (
                f"Based on everything discussed:\n{memory_context}\n\n"
                "Make your final accusation. Who is guilty and why?\n"
                'Respond as JSON: {"accused": "name", "reason": "why"}\n'
            )
        if final_phase == "vote":
            return (
                f"Based on everything discussed:\n{memory_context}\n\n"
                "Cast your vote. Who should be eliminated?\n"
                'Respond as JSON: {"vote": "name", "reason": "why"}\n'
            )
        return (
            f"Based on everything discussed:\n{memory_context}\n\n"
            f"Final phase: {final_phase}. Respond in character."
        )

    def evaluate(self, result: ScenarioResult) -> dict[str, float]:
        scores: dict[str, float] = {}
        correct = self._config.get("correct_answer", "").lower()
        if not correct:
            return scores

        for agent_id, response in result.final_actions.items():
            text = response.lower()
            try:
                start = text.find("{")
                end = text.rfind("}")
                if start != -1 and end > start:
                    data = json.loads(text[start : end + 1])
                    accused = data.get("accused", data.get("killer", "")).lower()
                else:
                    accused = ""
            except (json.JSONDecodeError, ValueError):
                accused = ""

            if correct in accused or accused in correct:
                scores[agent_id] = self._scoring.get("correct_accusation", 10)
            else:
                scores[agent_id] = self._scoring.get("wrong_accusation", -5)

        return scores


def load_scenario(path: Path) -> Scenario:
    """Load a scenario from a YAML file."""
    return YAMLScenario(path)
