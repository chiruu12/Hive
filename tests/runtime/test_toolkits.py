"""Tests for the built-in MemoryToolkit and CommsToolkit."""

from pathlib import Path

from hive.tools.comms import CommsToolkit
from hive.tools.memory import MemoryToolkit


class TestMemoryToolkit:
    def test_set_and_get(self, tmp_path: Path):
        tk = MemoryToolkit(path=tmp_path, agent_id="agent-1")
        tools = tk.get_tools()
        names = {t.name for t in tools}
        assert "memory_set" in names
        assert "memory_get" in names

    def test_set_get_roundtrip(self, tmp_path: Path):
        tk = MemoryToolkit(path=tmp_path, agent_id="agent-1")
        tk.memory_set("color", "blue")
        result = tk.memory_get("color")
        assert result == "blue"

    def test_get_missing_key(self, tmp_path: Path):
        tk = MemoryToolkit(path=tmp_path, agent_id="agent-1")
        result = tk.memory_get("nonexistent")
        assert "not found" in result.lower()

    def test_persistence(self, tmp_path: Path):
        tk1 = MemoryToolkit(path=tmp_path, agent_id="agent-1")
        tk1.memory_set("key", "value")

        tk2 = MemoryToolkit(path=tmp_path, agent_id="agent-1")
        assert tk2.memory_get("key") == "value"

    def test_auto_generates_id(self, tmp_path: Path):
        tk = MemoryToolkit(path=tmp_path)
        tk.memory_set("test", "value")
        assert tk._agent_id.startswith("agent-")

    def test_bind_sets_id(self, tmp_path: Path):
        tk = MemoryToolkit(path=tmp_path)
        tk.bind("my-agent")
        tk.memory_set("key", "val")
        assert (tmp_path / "my-agent.json").exists()

    def test_no_args(self):
        tk = MemoryToolkit()
        assert tk._dir.exists()


class TestCommsToolkit:
    def test_send_and_read(self, tmp_path: Path):
        sender = CommsToolkit(path=tmp_path, agent_id="agent-a")
        receiver = CommsToolkit(path=tmp_path, agent_id="agent-b")

        sender.send_message("agent-b", "hello from a")
        result = receiver.read_inbox()
        assert "hello from a" in result
        assert "agent-a" in result

    def test_empty_inbox(self, tmp_path: Path):
        tk = CommsToolkit(path=tmp_path, agent_id="agent-x")
        result = tk.read_inbox()
        assert "no messages" in result.lower()

    def test_tool_discovery(self, tmp_path: Path):
        tk = CommsToolkit(path=tmp_path, agent_id="agent-1")
        tools = tk.get_tools()
        names = {t.name for t in tools}
        assert "send_message" in names
        assert "read_inbox" in names

    def test_bind_sets_id(self, tmp_path: Path):
        tk = CommsToolkit(path=tmp_path)
        tk.bind("bound-agent")
        tk.send_message("other", "test msg")
        inbox_file = tmp_path / "other_inbox.jsonl"
        assert inbox_file.exists()
        assert "bound-agent" in inbox_file.read_text()
