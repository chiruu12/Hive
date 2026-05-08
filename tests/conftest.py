"""Shared fixtures for Hive tests."""

import tempfile
from pathlib import Path

import pytest

from hive.config import HiveConfig, set_config


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture(autouse=True)
def _reset_config():
    set_config(HiveConfig())
    yield
    set_config(HiveConfig())
