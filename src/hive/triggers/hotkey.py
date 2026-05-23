"""Global hotkey trigger using pynput."""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
import uuid
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

try:
    from pynput import keyboard

    _HAS_PYNPUT = True
except ImportError:
    keyboard = None  # type: ignore[assignment]
    _HAS_PYNPUT = False

_KEY_MAP: dict[str, str] = {
    "cmd": "cmd",
    "command": "cmd",
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "option": "alt",
    "shift": "shift",
}

_MODIFIER_ATTRS: dict[str, Any] = {}


def _init_modifier_attrs() -> None:
    if not _HAS_PYNPUT or _MODIFIER_ATTRS:
        return
    _MODIFIER_ATTRS.update(
        {
            "cmd": keyboard.Key.cmd,
            "ctrl": keyboard.Key.ctrl,
            "alt": keyboard.Key.alt,
            "shift": keyboard.Key.shift,
        }
    )


def _parse_combo(key_combo: str) -> tuple[frozenset[Any], Any]:
    """Parse 'cmd+shift+m' into (modifier_set, key)."""
    if not _HAS_PYNPUT:
        raise ImportError(
            "pynput is required for hotkeys. Install with: pip install hive-agent[hotkeys]"
        )
    _init_modifier_attrs()

    parts = [p.strip().lower() for p in key_combo.split("+")]
    modifiers: set[Any] = set()
    trigger_key: Any = None

    for part in parts:
        normalized = _KEY_MAP.get(part, part)
        if normalized in _MODIFIER_ATTRS:
            modifiers.add(_MODIFIER_ATTRS[normalized])
        else:
            if len(part) == 1:
                trigger_key = keyboard.KeyCode.from_char(part)
            else:
                trigger_key = getattr(keyboard.Key, part, None)
                if trigger_key is None:
                    trigger_key = keyboard.KeyCode.from_char(part)

    if trigger_key is None:
        raise ValueError(f"No trigger key found in combo: {key_combo!r}")

    return frozenset(modifiers), trigger_key


class HotkeyTrigger:
    """Global hotkey listener using pynput."""

    def __init__(self) -> None:
        if not _HAS_PYNPUT:
            raise ImportError(
                "pynput is required for hotkeys. Install with: pip install hive-agent[hotkeys]"
            )
        self._triggers: dict[str, dict[str, Any]] = {}
        self._listener: Any = None
        self._pressed: set[Any] = set()
        self._lock = threading.Lock()

    def register(
        self, key_combo: str, callback: Callable[..., object], name: str = ""
    ) -> str:
        trigger_id = str(uuid.uuid4())
        modifiers, key = _parse_combo(key_combo)
        with self._lock:
            self._triggers[trigger_id] = {
                "combo": key_combo,
                "modifiers": modifiers,
                "key": key,
                "callback": callback,
                "name": name or key_combo,
            }
        return trigger_id

    def unregister(self, trigger_id: str) -> None:
        with self._lock:
            self._triggers.pop(trigger_id, None)

    @property
    def active_triggers(self) -> list[dict[str, str]]:
        with self._lock:
            return [
                {"id": tid, "combo": t["combo"], "name": t["name"]}
                for tid, t in self._triggers.items()
            ]

    def start(self) -> None:
        if self._listener is not None:
            return
        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        self._pressed.clear()

    def _on_press(self, key: Any) -> None:
        self._pressed.add(key)
        with self._lock:
            for info in self._triggers.values():
                if info["key"] == key and info["modifiers"].issubset(self._pressed):
                    self._fire(info["callback"])

    def _on_release(self, key: Any) -> None:
        self._pressed.discard(key)

    def _fire(self, callback: Callable[..., object]) -> None:
        if inspect.iscoroutinefunction(callback):
            threading.Thread(
                target=lambda: asyncio.run(callback()), daemon=True
            ).start()
        else:
            threading.Thread(target=callback, daemon=True).start()
