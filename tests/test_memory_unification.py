"""Phase E — unified memory: toolkit, pursuit recall, goal generation, migration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hive.agents.existence import ExistenceLoop
from hive.agents.profile import AgentProfile
from hive.agents.suffering import SufferingState
from hive.config import HiveConfig, MemoryConfig, set_config
from hive.memory.migration import (
    ensure_legacy_migrated,
    legacy_json_path,
    migrate_legacy_json,
    migration_marker_path,
)
from hive.memory.recall import recall_snippets
from hive.memory.semantic import SemanticMemory
from hive.models.base import BaseProvider
from hive.runtime.agent import Agent
from hive.runtime.memory import PersistentMemory
from hive.runtime.types import GenerateResult, Message, Task
from hive.tools.memory import MemoryToolkit


class _MockProvider(BaseProvider):
    def __init__(self, responses: list[Message]):
        super().__init__("mock-model")
        self._responses = list(responses)
        self._call_count = 0
        self.calls: list[dict] = []

    @property
    def available(self) -> bool:
        return True

    async def generate_with_metadata(self, messages, tools=None, temperature=0.0, max_tokens=4096):
        self.calls.append({"messages": messages, "tools": tools, "temperature": temperature})
        response = (
            self._responses[self._call_count]
            if self._call_count < len(self._responses)
            else Message.assistant("done")
        )
        self._call_count += 1
        return GenerateResult(message=response, model="mock-model", input_tokens=1, output_tokens=1)


@pytest.fixture
def hive_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def unified_config() -> HiveConfig:
    cfg = HiveConfig(memory=MemoryConfig(unified=True))
    set_config(cfg)
    return cfg


@pytest.fixture
def legacy_config() -> HiveConfig:
    cfg = HiveConfig(memory=MemoryConfig(unified=False))
    set_config(cfg)
    return cfg


class TestMemoryToolkitUnified:
    def test_set_visible_in_semantic_recall(
        self, hive_dir: Path, unified_config: HiveConfig
    ) -> None:
        semantic = SemanticMemory(hive_dir, "agent-1")
        tk = MemoryToolkit(
            path=hive_dir / "agent_memory",
            agent_id="agent-1",
            semantic=semantic,
            hive_dir=hive_dir,
        )
        tk.memory_set("favorite_color", "ultramarine blue")

        records = semantic.recent(limit=5)
        assert any(r.thought == "ultramarine blue" for r in records)
        assert any(r.metadata.get("key") == "favorite_color" for r in records)

    @pytest.mark.asyncio
    async def test_recall_snippets_finds_stored_thought(self, hive_dir: Path) -> None:
        mem = SemanticMemory(hive_dir, "agent-1")
        await mem.store("Completed goal: refactor auth module", {"type": "goal_completed"})

        snippets = await recall_snippets(mem, "auth refactor", limit=3)
        assert any("auth" in s.lower() for s in snippets)


class TestLegacyJsonMigration:
    @pytest.mark.asyncio
    async def test_migrates_once(self, hive_dir: Path) -> None:
        legacy_dir = hive_dir / "agent_memory"
        legacy_dir.mkdir(parents=True)
        legacy = legacy_json_path(hive_dir, "agent-1", legacy_dir)
        legacy.write_text(json.dumps({"note": "legacy value"}))

        semantic = SemanticMemory(hive_dir, "agent-1")
        count = await migrate_legacy_json(semantic, hive_dir, "agent-1", legacy_dir)
        assert count == 1
        assert migration_marker_path(hive_dir, "agent-1").exists()

        count2 = await migrate_legacy_json(semantic, hive_dir, "agent-1", legacy_dir)
        assert count2 == 0
        assert semantic.count() == 1

    def test_sync_wrapper_idempotent(self, hive_dir: Path) -> None:
        legacy_dir = hive_dir / "agent_memory"
        legacy_dir.mkdir(parents=True)
        legacy_json_path(hive_dir, "agent-1", legacy_dir).write_text(
            json.dumps({"a": "1", "b": "2"})
        )
        semantic = SemanticMemory(hive_dir, "agent-1")
        first = ensure_legacy_migrated(semantic, hive_dir, "agent-1", legacy_dir)
        second = ensure_legacy_migrated(semantic, hive_dir, "agent-1", legacy_dir)
        assert first == 2
        assert second == 0


class TestPursuitMemoryRecall:
    @pytest.mark.asyncio
    async def test_pursuit_prompt_includes_relevant_memories(self, hive_dir: Path) -> None:
        mem = SemanticMemory(hive_dir, "coder")
        await mem.store("Always validate JWT signatures before trusting claims")

        persistent = PersistentMemory(agent_name="coder", hive_dir=hive_dir, semantic=mem)
        provider = _MockProvider([Message.assistant("done")])
        agent = Agent(name="coder", model=provider, memory=persistent)

        await agent.run(Task(instruction="Validate JWT signatures in authentication code"))

        first_call = provider.calls[0]["messages"]
        memory_msgs = [m for m in first_call if "Relevant memories" in (m.content or "")]
        assert memory_msgs, "Expected recalled memories in provider messages"
        assert any("JWT" in m.content for m in memory_msgs)


class TestGoalGenerationMemory:
    def test_build_prompt_includes_memory_snippets(self) -> None:
        loop = ExistenceLoop(
            agent_id="a1",
            profile=AgentProfile(name="tester", role="researcher"),
            provider=MagicMock(),
            store=MagicMock(),
            event_log=MagicMock(),
        )
        prompt = loop._build_prompt(
            suffering=SufferingState(agent_id="a1"),
            peers=[],
            recent_goals=[],
            tools_desc="",
            nudges=[],
            memory_snippets=["Previously fixed flaky login tests"],
        )
        assert "--- Relevant memories ---" in prompt
        assert "Previously fixed flaky login tests" in prompt


class TestLegacyJsonMode:
    def test_legacy_roundtrip(self, tmp_path: Path, legacy_config: HiveConfig) -> None:
        tk = MemoryToolkit(path=tmp_path, agent_id="agent-1", unified=False)
        tk.memory_set("color", "blue")
        assert tk.memory_get("color") == "blue"
        assert (tmp_path / "agent-1.json").exists()
