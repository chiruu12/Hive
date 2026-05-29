"""Typed exception hierarchy for Hive.

All Hive-specific errors derive from :class:`HiveError`, so callers can catch the
whole family with one ``except HiveError``. Where an error replaces a previously
raised builtin, it also subclasses that builtin so existing ``except ValueError`` /
``except FileNotFoundError`` handlers keep working.
"""

from __future__ import annotations


class HiveError(Exception):
    """Base class for all Hive-specific errors."""


class AgentNotFoundError(HiveError, ValueError):
    """An agent could not be resolved by id, name, or id-prefix."""


class ProfileNotFoundError(HiveError, FileNotFoundError):
    """A requested agent preset/profile does not exist."""
