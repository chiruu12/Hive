"""Central configuration — all tunables in one place."""

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, Field, field_validator

_dotenv_cache: dict[str, str | None] = {}


def _find_dotenv() -> Path | None:
    """Search CWD and parent directories for a .env file."""
    current = Path.cwd()
    for directory in [current, *current.parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
        if (directory / ".hive").is_dir():
            return candidate if candidate.is_file() else None
    return None


def _load_dotenv_safe() -> dict[str, str | None]:
    """Load .env values WITHOUT injecting into os.environ."""
    global _dotenv_cache
    if not _dotenv_cache:
        env_path = _find_dotenv()
        _dotenv_cache = dotenv_values(env_path) if env_path else {}
    return _dotenv_cache


def get_env(key: str, default: str = "") -> str:
    """Get a value from .env file first, then os.environ, never setting os.environ."""
    dot = _load_dotenv_safe()
    return dot.get(key) or os.environ.get(key, default)


def _parse_bool(value: str) -> bool:
    """Parse a truthy env-var string (bool('false') is True, so we can't use it)."""
    return value.strip().lower() in {"1", "true", "yes", "on"}


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

    @field_validator("threshold_constrained")
    @classmethod
    def _constrained_gt_prominent(cls, v: float, info: Any) -> float:
        prominent = info.data.get("threshold_prominent", 0.35)
        if v <= prominent:
            raise ValueError(
                f"threshold_constrained ({v}) must be > threshold_prominent ({prominent})"
            )
        return v

    @field_validator("threshold_dominant")
    @classmethod
    def _dominant_gt_constrained(cls, v: float, info: Any) -> float:
        constrained = info.data.get("threshold_constrained", 0.55)
        if v <= constrained:
            raise ValueError(
                f"threshold_dominant ({v}) must be > threshold_constrained ({constrained})"
            )
        return v

    @field_validator("threshold_crisis")
    @classmethod
    def _crisis_gt_dominant(cls, v: float, info: Any) -> float:
        dominant = info.data.get("threshold_dominant", 0.75)
        if v <= dominant:
            raise ValueError(f"threshold_crisis ({v}) must be > threshold_dominant ({dominant})")
        return v


class EconomyConfig(BaseModel):
    enabled: bool = True
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

    @field_validator("starting_balance")
    @classmethod
    def _balance_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"starting_balance must be >= 0, got {v}")
        return v


class DaemonConfig(BaseModel):
    heartbeat: int = 10
    max_retries: int = 2
    event_poll_interval: float = 0.3
    watch_refresh_rate: float = 0.5
    cycle_timeout: int = 300
    # Max agents whose cycles run concurrently per heartbeat (1 = sequential).
    max_concurrent_agents: int = 8

    @field_validator("heartbeat")
    @classmethod
    def _heartbeat_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"heartbeat must be >= 1, got {v}")
        return v

    @field_validator("max_concurrent_agents")
    @classmethod
    def _concurrency_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"max_concurrent_agents must be >= 1, got {v}")
        return v

    @field_validator("cycle_timeout")
    @classmethod
    def _timeout_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"cycle_timeout must be >= 0, got {v}")
        return v


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
    # fsync every event-log append for crash durability (one fsync per event).
    event_log_fsync: bool = False

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

        env_map: dict[str, tuple[str, str | None, Callable[[str], Any]]] = {
            "HIVE_HEARTBEAT": ("daemon", "heartbeat", int),
            "HIVE_MAX_RETRIES": ("daemon", "max_retries", int),
            "HIVE_DEFAULT_MODEL": ("model", "default_model", str),
            "HIVE_STARTING_BALANCE": ("economy", "starting_balance", float),
            "HIVE_PROFILES_DIR": ("profiles_dir", None, str),
            "HIVE_LOGS_DIR": ("logs_dir", None, str),
            "HIVE_EVENT_LOG_FSYNC": ("event_log_fsync", None, _parse_bool),
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

    def validate_environment(self) -> list[str]:
        """Check API keys for configured models. Returns a list of warnings."""
        warnings: list[str] = []
        model_key_map = {
            "claude-": "ANTHROPIC_API_KEY",
            "gpt-": "OPENAI_API_KEY",
            "groq:": "GROQ_API_KEY",
            "fireworks:": "FIREWORKS_API_KEY",
            "openrouter:": "OPENROUTER_API_KEY",
        }
        default = self.model.default_model
        for prefix, key_name in model_key_map.items():
            if default.startswith(prefix) and not get_env(key_name):
                warnings.append(f"default_model={default!r} requires {key_name} but it is not set")
        return warnings


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
