"""Central configuration — all tunables in one place."""

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class SufferingConfig(BaseModel):
    threshold_prominent: float = 0.35
    threshold_constrained: float = 0.55
    threshold_dominant: float = 0.75
    threshold_crisis: float = 0.90
    max_stressors: int = 5
    initial_severity: float = 0.20
    crisis_reset_after: int = 3
    escalation_rates: dict[str, float] = Field(
        default_factory=lambda: {
            "futility": 0.025,
            "invisibility": 0.030,
            "repeated_failure": 0.040,
            "purposelessness": 0.035,
            "identity_violation": 0.060,
            "existential_threat": 0.070,
        }
    )


class EconomyConfig(BaseModel):
    starting_balance: float = 100.0
    skill_course_cost: float = 80.0
    skill_increment: float = 0.25
    lottery_cost: float = 10.0
    lottery_win_chance: float = 0.05
    lottery_payout: float = 200.0
    blackjack_win_rate: float = 0.48
    default_gamble_wager: float = 10.0
    learnable_skills: list[str] = Field(
        default_factory=lambda: [
            "code_review",
            "teaching",
            "architecture",
            "analysis",
            "writing",
            "debugging",
        ]
    )


class DaemonConfig(BaseModel):
    heartbeat: int = 10
    max_retries: int = 2
    event_poll_interval: float = 0.3
    watch_refresh_rate: float = 0.5


class ModelConfig(BaseModel):
    default_model: str = "claude-haiku-4-5"
    planning_model: str = "claude-sonnet-4-6"
    max_tokens: int = 4096
    temperature: float = 0.0
    ollama_base_url: str = "http://localhost:11434"


class HiveConfig(BaseModel):
    """Root configuration for all of Hive."""

    suffering: SufferingConfig = SufferingConfig()
    economy: EconomyConfig = EconomyConfig()
    daemon: DaemonConfig = DaemonConfig()
    model: ModelConfig = ModelConfig()
    profiles_dir: str = ""
    logs_dir: str = "logs"

    @classmethod
    def load(cls, hive_dir: Path | None = None) -> "HiveConfig":
        """Load config from .hive/config.yaml, env vars, then defaults."""
        data: dict[str, Any] = {}

        if hive_dir:
            config_path = hive_dir / "config.yaml"
            if config_path.exists():
                with open(config_path) as f:
                    file_data = yaml.safe_load(f) or {}
                data.update(file_data)

        env_map = {
            "HIVE_HEARTBEAT": ("daemon", "heartbeat", int),
            "HIVE_MAX_RETRIES": ("daemon", "max_retries", int),
            "HIVE_DEFAULT_MODEL": ("model", "default_model", str),
            "HIVE_MAX_TURNS": ("model", "max_turns", int),
            "HIVE_SESSION_TIMEOUT": ("model", "session_timeout", int),
            "HIVE_STARTING_BALANCE": ("economy", "starting_balance", float),
            "HIVE_PROFILES_DIR": ("profiles_dir", None, str),
            "HIVE_LOGS_DIR": ("logs_dir", None, str),
        }

        for env_key, (section, field, cast) in env_map.items():
            val = os.environ.get(env_key)
            if val is not None:
                if field:
                    data.setdefault(section, {})[field] = cast(val)
                else:
                    data[section] = cast(val)

        return cls(**data)

    def save(self, hive_dir: Path) -> None:
        """Write config to .hive/config.yaml."""
        config_path = hive_dir / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False, sort_keys=False)


_config: HiveConfig | None = None


def get_config() -> HiveConfig:
    global _config
    if _config is None:
        _config = HiveConfig.load()
    return _config


def set_config(config: HiveConfig) -> None:
    global _config
    _config = config


def load_config(hive_dir: Path | None = None) -> HiveConfig:
    config = HiveConfig.load(hive_dir)
    set_config(config)
    return config
