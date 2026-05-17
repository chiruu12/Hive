"""Agent notepad — persistent scratchpad with configurable presets."""

from __future__ import annotations

import importlib.resources
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from hive.tools.base import Toolkit, tool


def _load_preset_yaml() -> dict[str, Any]:
    try:
        ref = importlib.resources.files("hive.tools.notepad") / "presets.yaml"
        result: dict[str, Any] = yaml.safe_load(ref.read_text()) or {}
        return result
    except Exception:
        presets_path = Path(__file__).parent / "presets.yaml"
        if presets_path.exists():
            result = yaml.safe_load(presets_path.read_text()) or {}
            return result
        return {}


_PRESET_DATA = _load_preset_yaml()


class Preset:
    """Notepad preset — defines what guidance the agent gets."""

    def __init__(self, name: str, instructions: str):
        self.name = name
        self.instructions = instructions

    def __repr__(self) -> str:
        return f"Preset({self.name!r})"

    @classmethod
    def default(cls) -> Preset:
        data = _PRESET_DATA.get("default", {})
        return cls(name="default", instructions=data.get("instructions", "").strip())

    @classmethod
    def journal(cls) -> Preset:
        data = _PRESET_DATA.get("journal", {})
        return cls(name="journal", instructions=data.get("instructions", "").strip())

    @classmethod
    def evolution(cls) -> Preset:
        data = _PRESET_DATA.get("evolution", {})
        return cls(name="evolution", instructions=data.get("instructions", "").strip())

    @classmethod
    def tool_requests(cls) -> Preset:
        data = _PRESET_DATA.get("tool_requests", {})
        return cls(name="tool_requests", instructions=data.get("instructions", "").strip())

    @classmethod
    def custom(cls, instructions: str) -> Preset:
        return cls(name="custom", instructions=instructions)


class NotepadManager:
    """Manages file-backed notepads for agents."""

    def __init__(self, hive_dir: Path):
        self._journals_dir = hive_dir / "journals"
        self._journals_dir.mkdir(parents=True, exist_ok=True)

    def _agent_dir(self, agent_id: str) -> Path:
        d = self._journals_dir / agent_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def read(self, agent_id: str) -> str:
        path = self._agent_dir(agent_id) / "notepad.md"
        if not path.exists():
            return ""
        return path.read_text()

    def write(self, agent_id: str, content: str) -> str:
        path = self._agent_dir(agent_id) / "notepad.md"
        ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        entry = f"\n---\n[{ts}]\n{content}\n"
        with open(path, "a") as f:
            f.write(entry)
        return f"Written at {ts}"

    def clear(self, agent_id: str) -> str:
        path = self._agent_dir(agent_id) / "notepad.md"
        path.write_text("")
        return "Notepad cleared."

    def read_other(self, target_agent_id: str) -> str:
        path = self._journals_dir / target_agent_id / "notepad.md"
        if not path.exists():
            return f"No notepad found for agent {target_agent_id}."
        return path.read_text()

    def list_agents_with_journals(self) -> list[str]:
        if not self._journals_dir.exists():
            return []
        return [d.name for d in self._journals_dir.iterdir() if d.is_dir()]

    def get_tail(self, agent_id: str, max_chars: int = 500) -> str:
        content = self.read(agent_id)
        if not content:
            return ""
        if len(content) <= max_chars:
            return content
        return "..." + content[-max_chars:]


class NotepadToolkit(Toolkit):
    """Persistent notepad for agents. Behavior guided by a Preset.

    Usage:
        # Simplest — auto-creates storage, auto-generates agent ID
        tk = NotepadToolkit()

        # With preset
        tk = NotepadToolkit(preset=Preset.journal())

        # With custom storage path
        tk = NotepadToolkit(path="/my/project/.hive/journals")

        # Daemon usage (manager shared across agents)
        tk = NotepadToolkit(manager=shared_manager)
    """

    def __init__(
        self,
        preset: Preset | None = None,
        path: str | Path | None = None,
        manager: NotepadManager | None = None,
    ):
        if manager:
            self._manager = manager
        else:
            storage = Path(path) if path else Path.cwd() / ".hive"
            self._manager = NotepadManager(storage)
        self._agent_id = ""
        self._preset = preset or Preset.default()

    def bind(self, agent_id: str) -> None:
        self._agent_id = agent_id

    def _ensure_id(self) -> str:
        if not self._agent_id:
            self._agent_id = f"agent-{uuid4().hex[:8]}"
        return self._agent_id

    @property
    def manager(self) -> NotepadManager:
        return self._manager

    @property
    def instructions(self) -> str:
        return self._preset.instructions

    @property
    def preset(self) -> Preset:
        return self._preset

    @tool()
    def write_notepad(self, content: str) -> str:
        """Write an entry to your notepad. Persists across cycles."""
        return self._manager.write(self._ensure_id(), content)

    @tool()
    def read_notepad(self) -> str:
        """Read your notepad contents."""
        content = self._manager.read(self._ensure_id())
        return content if content else "Your notepad is empty."

    @tool()
    def clear_notepad(self) -> str:
        """Clear your notepad and start fresh."""
        return self._manager.clear(self._ensure_id())

    @tool()
    def read_agent_notepad(self, agent_id: str) -> str:
        """Read another agent's notepad."""
        return self._manager.read_other(agent_id)
