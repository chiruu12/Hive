"""Tests for the built-in WorldToolkit, MemoryToolkit, CommsToolkit."""

from pathlib import Path

from hive.runtime.toolkits import CommsToolkit, MemoryToolkit


class TestMemoryToolkit:
    def test_set_and_get(self, tmp_path: Path):
        tk = MemoryToolkit(tmp_path, "agent-1")
        tools = tk.get_tools()
        names = {t.name for t in tools}
        assert "memory_set" in names
        assert "memory_get" in names

    def test_set_get_roundtrip(self, tmp_path: Path):
        tk = MemoryToolkit(tmp_path, "agent-1")
        tk.memory_set("color", "blue")
        result = tk.memory_get("color")
        assert result == "blue"

    def test_get_missing_key(self, tmp_path: Path):
        tk = MemoryToolkit(tmp_path, "agent-1")
        result = tk.memory_get("nonexistent")
        assert "not found" in result.lower()

    def test_persistence(self, tmp_path: Path):
        tk1 = MemoryToolkit(tmp_path, "agent-1")
        tk1.memory_set("key", "value")

        tk2 = MemoryToolkit(tmp_path, "agent-1")
        assert tk2.memory_get("key") == "value"


class TestCommsToolkit:
    def test_send_and_read(self, tmp_path: Path):
        sender = CommsToolkit(tmp_path, "agent-a")
        receiver = CommsToolkit(tmp_path, "agent-b")

        sender.send_message("agent-b", "hello from a")
        result = receiver.read_inbox()
        assert "hello from a" in result
        assert "agent-a" in result

    def test_empty_inbox(self, tmp_path: Path):
        tk = CommsToolkit(tmp_path, "agent-x")
        result = tk.read_inbox()
        assert "no messages" in result.lower()

    def test_tool_discovery(self, tmp_path: Path):
        tk = CommsToolkit(tmp_path, "agent-1")
        tools = tk.get_tools()
        names = {t.name for t in tools}
        assert "send_message" in names
        assert "read_inbox" in names
