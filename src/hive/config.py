"""Central configuration — all tunables in one place."""

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

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
    # When pursuit hits profile max_steps: ``continue`` keeps the goal active for
    # the next heartbeat; ``abandon`` marks it abandoned (legacy fail-fast).
    max_steps_policy: Literal["continue", "abandon"] = "continue"
    max_retries: int = 2
    cycle_timeout: int = 300
    # Max agents whose cycles run concurrently per heartbeat (1 = sequential).
    max_concurrent_agents: int = 8
    # Per-tool wall-clock limit (seconds); 0 disables. Stops one hung tool from
    # consuming the whole (coarser) cycle_timeout and abandoning the goal.
    tool_timeout: float = 60.0
    # Daemon-level cost budget. 0 = unlimited (no kill-switch).
    budget_usd: float = 0.0
    budget_tokens: int = 0
    # ``reserve`` holds estimated capacity before LLM calls (hard ceiling under
    # concurrency). ``record_only`` disables reservation (legacy overshoot window).
    budget_mode: Literal["reserve", "record_only"] = "reserve"
    # Default reservation estimates per phase (used before LLM calls).
    budget_reserve_usd_generation: float = 0.05
    budget_reserve_usd_pursuit: float = 0.10
    budget_reserve_tokens_generation: int = 100
    budget_reserve_tokens_pursuit: int = 500
    # Persist spent totals to .hive/budget.json across daemon restarts.
    budget_persist: bool = False
    # When True, ``hive config --validate`` warns if both budget limits are zero.
    warn_unlimited_budget: bool = False
    # When True (default), built-in safety guards block phases on internal errors
    # instead of failing open. Set False to restore legacy fail-open behavior.
    guards_fail_closed: bool = True
    # Optional file paths whose mtime changes wake the daemon mid-heartbeat.
    # Each path gets a FileWakeSource; empty list (default) registers none.
    watch_files: list[str] = Field(default_factory=list)
    # When True (default), pursuit reloads persisted ReAct transcript for the
    # active goal instead of starting from a single-shot user message each cycle.
    pursuit_resume: bool = True
    # Hard cap on messages stored per goal transcript (drop-oldest when exceeded).
    pursuit_transcript_max_messages: int = 200
    # Poll interval (seconds) for wake sources (A2A, nudges, watch files).
    wake_poll_interval: float = 1.0
    # Reuse built toolkit instances per agent across heartbeat cycles.
    toolkit_cache: bool = True
    # When True (default), active goals and pursuit transcripts survive daemon
    # stop/start. Set False to restore legacy abandon-on-restart cleanup.
    preserve_active_goals_on_restart: bool = True
    # When True (default), cycle timeout parks the agent without abandoning the
    # goal or deleting its pursuit transcript.
    preserve_active_goals_on_timeout: bool = True

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

    @field_validator("tool_timeout")
    @classmethod
    def _tool_timeout_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"tool_timeout must be >= 0, got {v}")
        return v

    @field_validator("pursuit_transcript_max_messages")
    @classmethod
    def _transcript_cap_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"pursuit_transcript_max_messages must be >= 1, got {v}")
        return v

    @field_validator("wake_poll_interval")
    @classmethod
    def _wake_poll_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"wake_poll_interval must be > 0, got {v}")
        return v


class ApprovalConfig(BaseModel):
    """Human-in-the-loop tool-approval policy.

    Disabled by default so existing single-user/local runs are unchanged. When
    enabled, a tool is gated if it is declared ``@tool(requires_approval=True)`` or
    its name is in ``require_for`` -- unless its name is in ``auto_approve``.
    """

    enabled: bool = False
    # Tool names always gated regardless of their decorator flag (ops override).
    require_for: list[str] = Field(default_factory=list)
    # Tool names never gated, overriding a tool's own requires_approval flag.
    auto_approve: list[str] = Field(default_factory=list)
    # Auto-deny a pending approval after this many heartbeat cycles (0 = wait forever).
    timeout_cycles: int = 0

    @field_validator("timeout_cycles")
    @classmethod
    def _timeout_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"timeout_cycles must be >= 0, got {v}")
        return v


class GuardrailConfig(BaseModel):
    """Content guardrails on model input/output.

    Disabled by default. When enabled, a PII guardrail (redacts output by default)
    and a prompt-injection guardrail (blocks input by default) run around the model.
    Actions are ``flag`` (log only), ``redact`` (mask matches), or ``block``.
    """

    enabled: bool = False
    pii: bool = True
    prompt_injection: bool = True
    pii_action: Literal["flag", "redact", "block"] = "redact"
    injection_action: Literal["flag", "redact", "block"] = "block"


class ToolsConfig(BaseModel):
    """Sandbox knobs for the built-in file and shell toolkits."""

    # Pass the full parent environment (including API keys and other secrets)
    # to agent-run shell commands. Off by default: provider credentials must
    # not be readable via `env` inside an agent's shell.
    shell_pass_env: bool = False
    # DEV_COMMANDS includes python, node, curl, wget, and other commands that
    # enable arbitrary code execution. Default to False so agents must opt in.
    shell_allow_dev_commands: bool = False
    # Refuse file reads/writes beyond this many bytes (guards against OOM).
    file_max_read_bytes: int = 10_000_000
    file_max_write_bytes: int = 10_000_000
    # Toolkit allowlist for spawned sub-agents (``spawned_by`` set). ``None``
    # uses the secure built-in default in :mod:`hive.daemon.toolkit_factory`
    # (no shell, delegation, schedule, orchestrator, plugins, etc.). Parent
    # agents always receive the full toolkit set.
    sub_agent_toolkits: list[str] | None = None

    @field_validator("file_max_read_bytes", "file_max_write_bytes")
    @classmethod
    def _caps_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"file size caps must be >= 1, got {v}")
        return v


class PluginsConfig(BaseModel):
    """Plugin toolkit loading from ``.hive/plugins/`` (and the parent ``plugins/``).

    Plugins execute arbitrary Python with full process privileges -- there is no
    sandbox. An agent can write ``.hive/plugins/*.py`` via the file toolkit and
    the daemon hot-loads new plugin files every 10 cycles.

    ``allowlist`` (filenames or stems) restricts which files load; empty means
    all, preserving the documented drop-in workflow when plugins are enabled.

    Default is ``False`` for security. Set ``enabled: true`` explicitly when
    you trust the plugin directory contents.
    """

    enabled: bool = False
    allowlist: list[str] = Field(default_factory=list)


class ServerConfig(BaseModel):
    """REST API server (`hive serve`) hardening knobs.

    All defaults preserve the local-first, zero-config behavior: no auth, no
    CORS, sessions never expire. Set ``api_key`` (or ``HIVE_API_KEY``) before
    exposing the server beyond localhost.
    """

    # Shared bearer key checked against the X-Hive-Key header on every route
    # except /healthz and the static UI/docs shells. Empty disables auth.
    api_key: str = ""
    # Allowed CORS origins; empty mounts no CORS middleware.
    cors_origins: list[str] = Field(default_factory=list)
    # Mark running sessions 'expired' once idle longer than this many hours
    # (enforced by the retention janitor and on session resolve). 0 = never.
    session_ttl_hours: int = 0

    @field_validator("session_ttl_hours")
    @classmethod
    def _ttl_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"session_ttl_hours must be >= 0, got {v}")
        return v


class RetentionConfig(BaseModel):
    """Periodic cleanup of terminal housekeeping rows (off by default).

    When enabled, the daemon deletes resolved approvals, fired alarms,
    delivered nudges, finished sessions, and finished delegations older than
    ``days``, and auto-denies pending approvals of DEAD agents. Pending work
    and the agents/goals tables are never touched.

    ``max_runs`` limits how many run directories are kept. Oldest runs are
    deleted first.  ``0`` means unlimited.
    """

    enabled: bool = False
    days: int = 30
    interval_cycles: int = 100
    max_runs: int = 50

    @field_validator("days", "interval_cycles")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"retention values must be >= 1, got {v}")
        return v


class ModelConfig(BaseModel):
    default_model: str = "claude-haiku-4-5"
    planning_model: str = "claude-sonnet-4-6"
    max_tokens: int = 4096
    temperature: float = 0.0
    ollama_base_url: str = "http://localhost:11434"


class MemoryConfig(BaseModel):
    """Agent memory backend selection."""

    # When True (default), MemoryToolkit and daemon pursuit share SemanticMemory
    # at ``<hive_dir>/memory/<agent_id>/``. Legacy JSON KV files migrate once.
    unified: bool = True


class HiveConfig(BaseModel):
    """Root configuration for all of Hive."""

    suffering: SufferingConfig = SufferingConfig()
    economy: EconomyConfig = EconomyConfig()
    daemon: DaemonConfig = DaemonConfig()
    memory: MemoryConfig = MemoryConfig()
    model: ModelConfig = ModelConfig()
    approval: ApprovalConfig = ApprovalConfig()
    guardrails: GuardrailConfig = GuardrailConfig()
    tools: ToolsConfig = ToolsConfig()
    plugins: PluginsConfig = PluginsConfig()
    retention: RetentionConfig = RetentionConfig()
    server: ServerConfig = ServerConfig()
    profiles_dir: str = ""
    logs_dir: str = "logs"
    # fsync every event-log append for crash durability (one fsync per event).
    event_log_fsync: bool = False
    # Seed for the world-simulation RNG (life-event rolls, luck, gambling). None
    # draws from system entropy (the default). Set an int for reproducible runs;
    # the value is recorded in each run's manifest.json. Note: this seeds the
    # stochastic *world* layer, not LLM outputs (which are not deterministic).
    seed: int | None = None

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
            "HIVE_SEED": ("seed", None, int),
            "HIVE_API_KEY": ("server", "api_key", str),
            "HIVE_BUDGET_USD": ("daemon", "budget_usd", float),
            "HIVE_BUDGET_TOKENS": ("daemon", "budget_tokens", int),
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


# --- Config hot-reload policy (Phase G) ---

ReloadStatus = Literal["applied", "restart_required"]

# Keys the running daemon applies from disk each heartbeat (via ``HiveDaemon.reload_config``).
_HOT_RELOAD_PATHS: frozenset[str] = frozenset(
    {
        "daemon.heartbeat",
        "daemon.cycle_timeout",
        "daemon.max_concurrent_agents",
        "daemon.wake_poll_interval",
        "daemon.tool_timeout",
        "daemon.max_steps_policy",
        "daemon.pursuit_resume",
        "daemon.pursuit_transcript_max_messages",
        "retention.enabled",
        "retention.days",
        "retention.interval_cycles",
        "retention.max_runs",
        "event_log_fsync",
    }
)

# Prefixes that require a daemon restart to take effect safely.
_RESTART_PREFIXES: tuple[str, ...] = (
    "guardrails.",
    "approval.",
    "plugins.",
    "tools.",
    "daemon.budget",
    "daemon.guards_fail_closed",
    "daemon.watch_files",
    "daemon.toolkit_cache",
    "economy.",
    "model.",
    "memory.",
    "server.",
    "suffering.",
)


def flatten_patch_keys(patch: dict[str, Any], prefix: str = "") -> set[str]:
    """Return dot-paths for every leaf key in a nested PATCH body."""
    keys: set[str] = set()
    for key, value in patch.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            keys.update(flatten_patch_keys(value, path))
        else:
            keys.add(path)
    return keys


def classify_config_reload(keys: set[str]) -> dict[str, ReloadStatus]:
    """Classify each patched key as hot-reloadable or restart-required."""
    result: dict[str, ReloadStatus] = {}
    for key in sorted(keys):
        if key in _HOT_RELOAD_PATHS:
            result[key] = "applied"
        elif key in {"seed", "profiles_dir"}:
            result[key] = "restart_required"
        elif any(key.startswith(prefix) for prefix in _RESTART_PREFIXES):
            result[key] = "restart_required"
        elif key.startswith("daemon."):
            # Unknown daemon.* keys default to restart for safety.
            result[key] = "restart_required"
        else:
            result[key] = "restart_required"
    return result


def reload_config_from_disk(hive_dir: Path | None = None) -> HiveConfig:
    """Reload ``.hive/config.yaml`` from disk and refresh the process-wide cache."""
    config = HiveConfig.load(hive_dir)
    set_config(config)
    return config


def load_persisted_config(hive_dir: Path) -> dict[str, Any]:
    """Load raw YAML from disk without env overrides."""
    config_path = hive_dir / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def resolve_logs_dir(hive_dir: Path, override: Path | None = None) -> Path:
    """Resolve the run-log directory from config or an explicit override."""
    if override is not None:
        return override
    cfg = HiveConfig.load(hive_dir)
    logs = cfg.logs_dir or "logs"
    path = Path(logs).expanduser()
    return path if path.is_absolute() else (hive_dir.parent / path)


def restart_required_field_paths() -> list[str]:
    """Known config paths/prefixes that require daemon restart (not hot-reloaded)."""
    restart: set[str] = {"seed", "profiles_dir", "logs_dir"}
    restart.update(
        {
            "daemon.max_retries",
            "daemon.budget_usd",
            "daemon.budget_tokens",
            "daemon.budget_mode",
            "daemon.budget_persist",
            "daemon.guards_fail_closed",
            "daemon.watch_files",
            "daemon.toolkit_cache",
            "daemon.preserve_active_goals_on_restart",
            "daemon.preserve_active_goals_on_timeout",
        }
    )
    restart.update(prefix.rstrip(".") for prefix in _RESTART_PREFIXES)
    return sorted(restart)


def config_truth_views(hive_dir: Path) -> dict[str, Any]:
    """Return persisted, effective, and live config snapshots for operators."""
    persisted = load_persisted_config(hive_dir)
    effective = HiveConfig.load(hive_dir).model_dump(mode="json")
    live: dict[str, Any] | None = None
    if _config is not None:
        live = _config.model_dump(mode="json")
    return {
        "persisted": persisted,
        "effective": effective,
        "live": live,
        "restart_required_fields": restart_required_field_paths(),
    }


def apply_config_patch(
    hive_dir: Path,
    patch: dict[str, Any],
    *,
    hot_reload: Callable[[], None] | None = None,
) -> tuple[dict[str, Any], dict[str, ReloadStatus]]:
    """Merge ``patch`` into ``.hive/config.yaml``, validate, save, and classify reload."""
    config_path = hive_dir / "config.yaml"
    data: dict[str, Any] = load_persisted_config(hive_dir)
    patched_keys = flatten_patch_keys(patch)

    def _deep_merge(base: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        for merge_key, merge_value in body.items():
            if isinstance(merge_value, dict) and isinstance(base.get(merge_key), dict):
                _deep_merge(base[merge_key], merge_value)
            else:
                base[merge_key] = merge_value
        return base

    _deep_merge(data, patch)
    HiveConfig(**data)
    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)

    reload_status = classify_config_reload(patched_keys)
    if hot_reload is not None and any(s == "applied" for s in reload_status.values()):
        hot_reload()
        reload_config_from_disk(hive_dir)
    return data, reload_status
