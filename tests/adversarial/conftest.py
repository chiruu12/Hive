"""Shared configuration for adversarial / resilience tests."""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test in this directory for CI filtering and --strict-markers."""
    for item in items:
        item.add_marker(pytest.mark.adversarial)
