"""Tests for Hive programmatic API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from hive.api import Hive
from hive.config import HiveConfig, set_config
from hive.runtime.types import GenerateResult, Message, ToolCall


class MockAPIProvider:
    def __init__(self) -> None:
        self._call_count = 0

    @property
    def available(self) -> bool:
        return True

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Message:
        result = await self.generate_with_metadata(
            messages, tools, temperature, max_tokens,
        )
        return result.message

    async def generate_with_metadata(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> GenerateResult:
        self._call_count += 1
        prompt = " ".join(m.content for m in messages).lower()

        if "what is the single most valuable" in prompt:
            content = json.dumps({
                "goal": "Learn API testing",
                "reasoning": "Improves reliability",
            })
            msg = Message.assistant(content)
        elif tools:
            msg = Message.assistant(
                "Storing.",
                [ToolCall(
                    id=f"tc-{self._call_count}", name="memory_set",
                    arguments={"key": "test", "value": "data"},
                )],
            )
        else:
            msg = Message.assistant("Done.")

        return GenerateResult(
            message=msg, model="mock", input_tokens=10,
            output_tokens=5, cost_usd=0.0, duration_ms=10,
        )


def _mock_provider(model_name: str) -> MockAPIProvider:
    return MockAPIProvider()


@pytest.fixture
def hive_root(tmp_path: Path) -> Path:
    cfg = HiveConfig()
    cfg.economy.enabled = False
    set_config(cfg)
    return tmp_path


class TestHiveInit:
    def test_creates_hive_dir(self, hive_root: Path) -> None:
        h = Hive(hive_root)
        h.init()
        assert (hive_root / ".hive").exists()
        assert (hive_root / ".hive" / "hive.db").exists()


class TestHiveSpawn:
    def test_spawn_returns_agent_id(self, hive_root: Path) -> None:
        h = Hive(hive_root)
        h.init()
        aid = h.spawn("coder")
        assert aid.startswith("coder-")

    def test_spawned_agent_in_status(self, hive_root: Path) -> None:
        h = Hive(hive_root)
        h.init()
        h.spawn("coder")
        agents = h.status()
        assert len(agents) == 1
        assert agents[0]["name"] == "coder"
        assert agents[0]["status"] == "idle"


class TestHiveStatus:
    def test_empty_hive(self, hive_root: Path) -> None:
        h = Hive(hive_root)
        h.init()
        assert h.status() == []

    def test_status_structure(self, hive_root: Path) -> None:
        h = Hive(hive_root)
        h.init()
        h.spawn("coder")
        agents = h.status()
        keys = set(agents[0].keys())
        assert keys == {
            "agent_id", "name", "role", "model", "status", "goal",
        }


class TestHiveKill:
    def test_kill_changes_status(self, hive_root: Path) -> None:
        h = Hive(hive_root)
        h.init()
        aid = h.spawn("coder")
        h.kill(aid)
        agents = h.status()
        assert agents[0]["status"] == "dead"


class TestHiveNudge:
    def test_nudge_stores_message(self, hive_root: Path) -> None:
        h = Hive(hive_root)
        h.init()
        aid = h.spawn("coder")
        h.nudge(aid, "Focus on testing")
        # Nudge is stored — no exception means success


class TestHiveResolveAgent:
    def test_resolve_by_name(self, hive_root: Path) -> None:
        h = Hive(hive_root)
        h.init()
        aid = h.spawn("coder")
        resolved = h._resolve_agent("coder")
        assert resolved == aid

    def test_resolve_by_id(self, hive_root: Path) -> None:
        h = Hive(hive_root)
        h.init()
        aid = h.spawn("coder")
        resolved = h._resolve_agent(aid)
        assert resolved == aid

    def test_resolve_by_prefix(self, hive_root: Path) -> None:
        h = Hive(hive_root)
        h.init()
        aid = h.spawn("coder")
        resolved = h._resolve_agent(aid[:10])
        assert resolved == aid

    def test_resolve_not_found(self, hive_root: Path) -> None:
        h = Hive(hive_root)
        h.init()
        with pytest.raises(ValueError, match="Agent not found"):
            h._resolve_agent("nonexistent")


class TestHiveStart:
    def test_bounded_run(self, hive_root: Path) -> None:
        h = Hive(hive_root)
        h.init()
        h.spawn("coder")

        with patch(
            "hive.daemon.loop.create_runtime_provider",
            side_effect=_mock_provider,
        ):
            h.start(cycles=1, heartbeat=0)

        agents = h.status()
        assert len(agents) == 1
