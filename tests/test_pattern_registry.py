"""Tests for the pattern registry."""

from __future__ import annotations

from typing import Any

import pytest

from hive.interactions.a2a import A2AStore
from hive.interactions.a2a_patterns import A2APattern
from hive.interactions.registry import (
    InteractionPatternRegistry,
    MemoryStrategyRegistry,
    PatternRegistry,
)


@pytest.fixture(autouse=True)
def _reset_registries():
    PatternRegistry._reset()
    InteractionPatternRegistry._reset()
    MemoryStrategyRegistry._reset()
    yield
    PatternRegistry._reset()
    InteractionPatternRegistry._reset()
    MemoryStrategyRegistry._reset()


class TestPatternRegistry:
    def test_default_has_five_patterns(self):
        reg = PatternRegistry.default()
        assert len(reg.list_patterns()) == 5
        assert set(reg.list_patterns()) == {"review", "mentor", "debate", "chain", "swarm"}

    def test_register_custom_pattern(self):
        class CustomPattern(A2APattern):
            async def execute(
                self,
                store: A2AStore,
                initiator: str,
                participants: list[str],
                context: str,
            ) -> dict[str, Any]:
                return {"pattern": "custom", "status": "ok"}

        reg = PatternRegistry.default()
        reg.register("custom", CustomPattern())
        assert "custom" in reg.list_patterns()
        assert len(reg.list_patterns()) == 6

    def test_get_pattern(self):
        reg = PatternRegistry.default()
        pattern = reg.get("review")
        assert pattern is not None

    def test_get_unknown_raises(self):
        reg = PatternRegistry.default()
        with pytest.raises(KeyError, match="Unknown pattern"):
            reg.get("nonexistent")

    def test_singleton_behavior(self):
        a = PatternRegistry.default()
        b = PatternRegistry.default()
        assert a is b


class TestInteractionPatternRegistry:
    def test_default_has_three_patterns(self):
        reg = InteractionPatternRegistry.default()
        assert set(reg.list_patterns()) == {"round_table", "pairs", "freeform"}

    def test_get_creates_instance(self):
        reg = InteractionPatternRegistry.default()
        pattern = reg.get("round_table")
        assert pattern is not None


class TestMemoryStrategyRegistry:
    def test_default_has_three_strategies(self):
        reg = MemoryStrategyRegistry.default()
        assert set(reg.list_strategies()) == {"full", "selective", "persona"}

    def test_get_creates_instance(self):
        reg = MemoryStrategyRegistry.default()
        strategy = reg.get("full")
        assert strategy is not None


class TestRunnerIntegration:
    def test_create_pattern_uses_registry(self):
        from hive.interactions.runner import create_pattern

        pattern = create_pattern("round_table")
        assert pattern is not None

    def test_create_pattern_fallback(self):
        from hive.interactions.runner import create_pattern

        pattern = create_pattern("nonexistent")
        assert pattern is not None

    def test_create_memory_uses_registry(self):
        from hive.interactions.runner import create_memory

        mem = create_memory("full")
        assert mem is not None

    def test_create_memory_fallback(self):
        from hive.interactions.runner import create_memory

        mem = create_memory("nonexistent")
        assert mem is not None
