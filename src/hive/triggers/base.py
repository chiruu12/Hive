"""Trigger protocol."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable


@runtime_checkable
class Trigger(Protocol):
    def register(self, key: str, callback: Callable[..., object], name: str = "") -> str: ...

    def unregister(self, trigger_id: str) -> None: ...
