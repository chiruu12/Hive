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
