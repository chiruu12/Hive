"""Tests for config system."""

import pytest
from pydantic import ValidationError

from hive.config import (
    DaemonConfig,
    EconomyConfig,
    HiveConfig,
    SufferingConfig,
    load_config,
    set_config,
)


def test_default_config():
    cfg = HiveConfig()
    assert cfg.daemon.heartbeat == 10
    assert cfg.suffering.threshold_crisis == 0.90
    assert cfg.economy.starting_balance == 100.0
    assert cfg.model.default_model == "claude-haiku-4-5"
    assert cfg.tools.sub_agent_toolkits is None


def test_config_from_yaml(tmp_dir):
    config_path = tmp_dir / "config.yaml"
    config_path.write_text("daemon:\n  heartbeat: 30\neconomy:\n  starting_balance: 500.0\n")
    cfg = HiveConfig.load(tmp_dir)
    assert cfg.daemon.heartbeat == 30
    assert cfg.economy.starting_balance == 500.0
    assert cfg.suffering.threshold_crisis == 0.90  # default preserved


def test_config_save_and_reload(tmp_dir):
    cfg = HiveConfig()
    cfg.daemon.heartbeat = 42
    cfg.save(tmp_dir)
    assert (tmp_dir / "config.yaml").exists()

    loaded = HiveConfig.load(tmp_dir)
    assert loaded.daemon.heartbeat == 42


def test_env_override(tmp_dir, monkeypatch):
    monkeypatch.setenv("HIVE_HEARTBEAT", "99")
    cfg = HiveConfig.load(tmp_dir)
    assert cfg.daemon.heartbeat == 99


def test_event_log_fsync_default_off():
    assert HiveConfig().event_log_fsync is False


def test_shell_allow_dev_commands_default_off():
    assert HiveConfig().tools.shell_allow_dev_commands is False


def test_plugins_enabled_default_off():
    assert HiveConfig().plugins.enabled is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", True), ("true", True), ("YES", True), ("on", True), ("0", False), ("false", False)],
)
def test_event_log_fsync_env_parse(tmp_dir, monkeypatch, value, expected):
    monkeypatch.setenv("HIVE_EVENT_LOG_FSYNC", value)
    cfg = HiveConfig.load(tmp_dir)
    assert cfg.event_log_fsync is expected


def test_set_and_get_config():
    from hive.config import get_config

    custom = HiveConfig()
    custom.daemon.heartbeat = 77
    set_config(custom)
    assert get_config().daemon.heartbeat == 77


def test_load_config_sets_global(tmp_dir):
    from hive.config import get_config

    config_path = tmp_dir / "config.yaml"
    config_path.write_text("daemon:\n  heartbeat: 55\n")
    load_config(tmp_dir)
    assert get_config().daemon.heartbeat == 55


def test_classify_config_reload_hot_and_restart():
    from hive.config import classify_config_reload

    status = classify_config_reload(
        {"daemon.heartbeat", "daemon.cycle_timeout", "guardrails.enabled"}
    )
    assert status["daemon.heartbeat"] == "applied"
    assert status["daemon.cycle_timeout"] == "applied"
    assert status["guardrails.enabled"] == "restart_required"


def test_classify_config_reload_unwired_keys_restart_required():
    from hive.config import classify_config_reload

    status = classify_config_reload(
        {
            "logs_dir",
            "daemon.max_retries",
        }
    )
    assert status["logs_dir"] == "restart_required"
    assert status["daemon.max_retries"] == "restart_required"


def test_flatten_patch_keys_nested():
    from hive.config import flatten_patch_keys

    keys = flatten_patch_keys({"daemon": {"heartbeat": 5, "budget_usd": 1.0}})
    assert keys == {"daemon.heartbeat", "daemon.budget_usd"}


def test_reload_config_from_disk(tmp_dir):
    from hive.config import get_config, reload_config_from_disk, set_config

    config_path = tmp_dir / "config.yaml"
    config_path.write_text("daemon:\n  heartbeat: 33\n  cycle_timeout: 120\n")
    set_config(HiveConfig())
    reload_config_from_disk(tmp_dir)
    assert get_config().daemon.heartbeat == 33
    assert get_config().daemon.cycle_timeout == 120


def test_daemon_reload_config_refreshes_cycle_timeout(tmp_dir):
    from hive.config import get_config
    from hive.daemon.loop import HiveDaemon

    config_path = tmp_dir / "config.yaml"
    config_path.write_text("daemon:\n  cycle_timeout: 60\n")
    daemon = HiveDaemon(tmp_dir, heartbeat=0, logs_dir=tmp_dir / "logs")
    assert get_config().daemon.cycle_timeout == 60

    config_path.write_text("daemon:\n  cycle_timeout: 45\n")
    daemon.reload_config()
    assert get_config().daemon.cycle_timeout == 45


def test_wake_poll_interval_default():
    assert DaemonConfig().wake_poll_interval == 1.0


def test_toolkit_cache_default_on():
    assert DaemonConfig().toolkit_cache is True


# --- Threshold ordering validation ---


def test_threshold_ordering_valid():
    cfg = SufferingConfig(
        threshold_prominent=0.2,
        threshold_constrained=0.4,
        threshold_dominant=0.6,
        threshold_crisis=0.8,
    )
    assert cfg.threshold_crisis == 0.8


def test_threshold_constrained_lte_prominent_invalid():
    with pytest.raises(ValidationError, match="threshold_constrained"):
        SufferingConfig(threshold_prominent=0.8, threshold_constrained=0.5)


def test_threshold_dominant_lte_constrained_invalid():
    with pytest.raises(ValidationError, match="threshold_dominant"):
        SufferingConfig(threshold_constrained=0.7, threshold_dominant=0.5)


def test_threshold_crisis_lte_dominant_invalid():
    with pytest.raises(ValidationError, match="threshold_crisis"):
        SufferingConfig(threshold_dominant=0.9, threshold_crisis=0.8)


# --- Heartbeat validation ---


def test_heartbeat_zero_invalid():
    with pytest.raises(ValidationError, match="heartbeat"):
        DaemonConfig(heartbeat=0)


def test_heartbeat_negative_invalid():
    with pytest.raises(ValidationError, match="heartbeat"):
        DaemonConfig(heartbeat=-1)


def test_heartbeat_one_valid():
    cfg = DaemonConfig(heartbeat=1)
    assert cfg.heartbeat == 1


def test_tool_timeout_negative_invalid():
    with pytest.raises(ValidationError, match="tool_timeout"):
        DaemonConfig(tool_timeout=-1.0)


def test_tool_timeout_zero_valid():
    cfg = DaemonConfig(tool_timeout=0.0)
    assert cfg.tool_timeout == 0.0


def test_tool_timeout_default():
    assert DaemonConfig().tool_timeout == 60.0


# --- Starting balance validation ---


def test_starting_balance_negative_invalid():
    with pytest.raises(ValidationError, match="starting_balance"):
        EconomyConfig(starting_balance=-10.0)


def test_starting_balance_zero_valid():
    cfg = EconomyConfig(starting_balance=0.0)
    assert cfg.starting_balance == 0.0


# --- Environment validation ---


def test_validate_environment_warns_missing_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import hive.config as _cfg_mod

    monkeypatch.setattr(_cfg_mod, "_dotenv_cache", {"ANTHROPIC_API_KEY": None})
    cfg = HiveConfig()
    warnings = cfg.validate_environment()
    assert any("ANTHROPIC_API_KEY" in w for w in warnings)


def test_validate_environment_no_warnings_for_local_model():
    cfg = HiveConfig()
    cfg.model.default_model = "ollama:llama3.2"
    warnings = cfg.validate_environment()
    assert not any("ANTHROPIC_API_KEY" in w for w in warnings)


# --- Equal thresholds (must be strictly increasing) ---


def test_threshold_equal_prominent_constrained_invalid():
    with pytest.raises(ValidationError, match="threshold_constrained"):
        SufferingConfig(threshold_prominent=0.5, threshold_constrained=0.5)


def test_threshold_equal_constrained_dominant_invalid():
    with pytest.raises(ValidationError, match="threshold_dominant"):
        SufferingConfig(threshold_constrained=0.6, threshold_dominant=0.6)


def test_threshold_equal_dominant_crisis_invalid():
    with pytest.raises(ValidationError, match="threshold_crisis"):
        SufferingConfig(threshold_dominant=0.8, threshold_crisis=0.8)


# --- Groq / Fireworks environment warnings ---


def test_validate_environment_warns_groq_missing_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    import hive.config as _cfg_mod

    monkeypatch.setattr(_cfg_mod, "_dotenv_cache", {"GROQ_API_KEY": None})
    cfg = HiveConfig()
    cfg.model.default_model = "groq:mixtral-8x7b"
    warnings = cfg.validate_environment()
    assert any("GROQ_API_KEY" in w for w in warnings)


def test_validate_environment_warns_fireworks_missing_key(monkeypatch):
    monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)
    import hive.config as _cfg_mod

    monkeypatch.setattr(_cfg_mod, "_dotenv_cache", {"FIREWORKS_API_KEY": None})
    cfg = HiveConfig()
    cfg.model.default_model = "fireworks:llama-v2"
    warnings = cfg.validate_environment()
    assert any("FIREWORKS_API_KEY" in w for w in warnings)


def test_secure_profile_example_validates():
    from pathlib import Path

    import yaml

    path = Path(__file__).resolve().parents[1] / "profiles" / "_secure.yaml.example"
    data = yaml.safe_load(path.read_text())
    cfg = HiveConfig(**data)
    assert cfg.guardrails.enabled is True
    assert cfg.approval.enabled is True
    assert cfg.tools.shell_allow_dev_commands is False
    assert cfg.plugins.enabled is False


def test_resolve_logs_dir_from_config(tmp_dir):
    from hive.config import resolve_logs_dir

    config_path = tmp_dir / "config.yaml"
    config_path.write_text("logs_dir: custom-logs\n")
    resolved = resolve_logs_dir(tmp_dir)
    assert resolved == tmp_dir.parent / "custom-logs"


def test_config_truth_views(tmp_dir):
    from hive.config import config_truth_views, set_config

    config_path = tmp_dir / "config.yaml"
    config_path.write_text("daemon:\n  heartbeat: 12\n")
    set_config(HiveConfig())
    views = config_truth_views(tmp_dir)
    assert views["persisted"]["daemon"]["heartbeat"] == 12
    assert views["effective"]["daemon"]["heartbeat"] == 12
    assert "restart_required_fields" in views


def test_apply_config_patch_writes_and_classifies(tmp_dir):
    from hive.config import apply_config_patch

    config_path = tmp_dir / "config.yaml"
    config_path.write_text("daemon:\n  heartbeat: 10\n")
    data, reload = apply_config_patch(tmp_dir, {"daemon": {"heartbeat": 20, "budget_usd": 5.0}})
    assert data["daemon"]["heartbeat"] == 20
    assert reload["daemon.heartbeat"] == "applied"
    assert reload["daemon.budget_usd"] == "restart_required"


def test_start_persists_cli_heartbeat(tmp_dir, monkeypatch):
    from hive.daemon.setup import initialize_hive

    monkeypatch.chdir(tmp_dir)
    initialize_hive(tmp_dir)
    hive_dir = tmp_dir / ".hive"

    cfg_before = HiveConfig.load(hive_dir)
    assert cfg_before.daemon.heartbeat == 10

    cfg_before.daemon.heartbeat = 7
    cfg_before.save(hive_dir)
    loaded = HiveConfig.load(hive_dir)
    assert loaded.daemon.heartbeat == 7
