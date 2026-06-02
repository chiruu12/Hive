"""Typed exception hierarchy for Hive.

All Hive-specific errors derive from :class:`HiveError`, so callers can catch the
whole family with one ``except HiveError``. Where an error replaces a previously
raised builtin, it also subclasses that builtin so existing ``except ValueError`` /
``except FileNotFoundError`` handlers keep working.
"""

from __future__ import annotations

from typing import Any


class HiveError(Exception):
    """Base class for all Hive-specific errors."""


class AgentNotFoundError(HiveError, ValueError):
    """An agent could not be resolved by id, name, or id-prefix."""


class ProfileNotFoundError(HiveError, FileNotFoundError):
    """A requested agent preset/profile does not exist."""


class MissingDependencyError(HiveError, ImportError):
    """An optional dependency for a feature/provider is not installed."""


def require_dependency(module: str, extra: str) -> Any:
    """Import ``module``, raising a clear :class:`MissingDependencyError` if absent.

    ``extra`` names the install extra that provides it, e.g. ``require_dependency
    ("openai", "openai")`` -> hint ``pip install 'hive-agent[openai]'``.
    """
    import importlib

    try:
        return importlib.import_module(module)
    except ImportError as e:
        raise MissingDependencyError(
            f"The '{module}' package is required for this feature but is not installed. "
            f"Install it with: pip install 'hive-agent[{extra}]'"
        ) from e


class StructuredParseError(HiveError, ValueError):
    """A model response could not be parsed/validated into the requested type.

    Carries the raw model text on :attr:`raw` so callers can inspect or log what
    the model actually returned.
    """

    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw
