"""Tests for config system."""

from hive.config import HiveConfig, load_config, set_config


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
