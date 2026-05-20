"""Pattern registries for A2A and interaction patterns."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from hive.interactions.a2a_patterns import A2APattern
    from hive.interactions.base import InteractionPattern, MemoryStrategy


class PatternRegistry:
    """Registry for A2A collaboration patterns (stores shared instances)."""

    _instance: ClassVar[PatternRegistry | None] = None

    def __init__(self) -> None:
        self._patterns: dict[str, A2APattern] = {}

    def register(self, name: str, pattern: A2APattern) -> None:
        """Register an A2A pattern by name."""
        self._patterns[name] = pattern

    def get(self, name: str) -> A2APattern:
        """Get a shared pattern instance by name."""
        if name not in self._patterns:
            raise KeyError(f"Unknown pattern: {name}")
        return self._patterns[name]

    def list_patterns(self) -> list[str]:
        """Return names of all registered patterns."""
        return list(self._patterns.keys())

    @classmethod
    def default(cls) -> PatternRegistry:
        if cls._instance is None:
            from hive.interactions.a2a_patterns import (
                ChainPattern,
                DebatePattern,
                MentorPattern,
                ReviewPattern,
                SwarmTaskPattern,
            )

            cls._instance = cls()
            cls._instance.register("review", ReviewPattern())
            cls._instance.register("mentor", MentorPattern())
            cls._instance.register("debate", DebatePattern())
            cls._instance.register("chain", ChainPattern())
            cls._instance.register("swarm", SwarmTaskPattern())
        return cls._instance

    @classmethod
    def _reset(cls) -> None:
        cls._instance = None


class InteractionPatternRegistry:
    """Registry for scenario-based interaction patterns (creates new instances per get)."""

    _instance: ClassVar[InteractionPatternRegistry | None] = None

    def __init__(self) -> None:
        self._patterns: dict[str, type[InteractionPattern]] = {}

    def register(self, name: str, pattern_cls: type[InteractionPattern]) -> None:
        """Register an interaction pattern class by name."""
        self._patterns[name] = pattern_cls

    def get(self, name: str) -> InteractionPattern:
        """Create and return a new pattern instance by name."""
        if name not in self._patterns:
            raise KeyError(f"Unknown interaction pattern: {name}")
        return self._patterns[name]()

    def list_patterns(self) -> list[str]:
        """Return names of all registered patterns."""
        return list(self._patterns.keys())

    @classmethod
    def default(cls) -> InteractionPatternRegistry:
        if cls._instance is None:
            from hive.interactions.patterns.freeform import FreeformPattern
            from hive.interactions.patterns.pairs import PairsPattern
            from hive.interactions.patterns.round_table import RoundTablePattern

            cls._instance = cls()
            cls._instance.register("round_table", RoundTablePattern)
            cls._instance.register("pairs", PairsPattern)
            cls._instance.register("freeform", FreeformPattern)
        return cls._instance

    @classmethod
    def _reset(cls) -> None:
        cls._instance = None


class MemoryStrategyRegistry:
    """Registry for interaction memory strategies."""

    _instance: ClassVar[MemoryStrategyRegistry | None] = None

    def __init__(self) -> None:
        self._strategies: dict[str, type[MemoryStrategy]] = {}

    def register(self, name: str, strategy_cls: type[MemoryStrategy]) -> None:
        """Register a memory strategy class by name."""
        self._strategies[name] = strategy_cls

    def get(self, name: str) -> MemoryStrategy:
        """Create and return a strategy instance by name."""
        if name not in self._strategies:
            raise KeyError(f"Unknown memory strategy: {name}")
        return self._strategies[name]()

    def list_strategies(self) -> list[str]:
        """Return names of all registered strategies."""
        return list(self._strategies.keys())

    @classmethod
    def default(cls) -> MemoryStrategyRegistry:
        if cls._instance is None:
            from hive.interactions.memory.full import FullMemory
            from hive.interactions.memory.persona import PersonaMemory
            from hive.interactions.memory.selective import SelectiveMemory

            cls._instance = cls()
            cls._instance.register("full", FullMemory)
            cls._instance.register("selective", SelectiveMemory)
            cls._instance.register("persona", PersonaMemory)
        return cls._instance

    @classmethod
    def _reset(cls) -> None:
        cls._instance = None
