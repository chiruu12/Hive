"""Tests for the NotepadManager, NotepadToolkit, and Preset system."""

from pathlib import Path

from hive.tools.notepad import NotepadManager, NotepadToolkit, Preset


class TestNotepadManager:
    def test_write_and_read(self, tmp_path: Path):
        manager = NotepadManager(tmp_path)
        manager.write("agent-1", "First observation")
        content = manager.read("agent-1")
        assert "First observation" in content

    def test_appends_with_timestamps(self, tmp_path: Path):
        manager = NotepadManager(tmp_path)
        manager.write("agent-1", "Entry one")
        manager.write("agent-1", "Entry two")
        content = manager.read("agent-1")
        assert "Entry one" in content
        assert "Entry two" in content
        assert content.count("---") >= 2

    def test_clear(self, tmp_path: Path):
        manager = NotepadManager(tmp_path)
        manager.write("agent-1", "Something")
        manager.clear("agent-1")
        content = manager.read("agent-1")
        assert content == ""

    def test_read_empty(self, tmp_path: Path):
        manager = NotepadManager(tmp_path)
        content = manager.read("nonexistent-agent")
        assert content == ""

    def test_read_other_agent(self, tmp_path: Path):
        manager = NotepadManager(tmp_path)
        manager.write("agent-a", "Thoughts of A")
        content = manager.read_other("agent-a")
        assert "Thoughts of A" in content

    def test_read_other_nonexistent(self, tmp_path: Path):
        manager = NotepadManager(tmp_path)
        content = manager.read_other("ghost-agent")
        assert "No notepad found" in content

    def test_list_agents_with_journals(self, tmp_path: Path):
        manager = NotepadManager(tmp_path)
        manager.write("agent-1", "note")
        manager.write("agent-2", "note")
        agents = manager.list_agents_with_journals()
        assert "agent-1" in agents
        assert "agent-2" in agents

    def test_get_tail(self, tmp_path: Path):
        manager = NotepadManager(tmp_path)
        manager.write("agent-1", "A" * 1000)
        tail = manager.get_tail("agent-1", max_chars=100)
        assert tail.startswith("...")
        assert len(tail) <= 104


class TestNotepadToolkit:
    def test_tool_discovery(self, tmp_path: Path):
        tk = NotepadToolkit(path=tmp_path)
        tools = tk.get_tools()
        names = {t.name for t in tools}
        assert "write_notepad" in names
        assert "read_notepad" in names
        assert "clear_notepad" in names
        assert "read_agent_notepad" in names

    def test_write_and_read(self, tmp_path: Path):
        tk = NotepadToolkit(path=tmp_path)
        tk.bind("agent-1")
        tk.write_notepad("Hello from toolkit")
        result = tk.read_notepad()
        assert "Hello from toolkit" in result

    def test_clear(self, tmp_path: Path):
        tk = NotepadToolkit(path=tmp_path)
        tk.bind("agent-1")
        tk.write_notepad("Some content")
        tk.clear_notepad()
        result = tk.read_notepad()
        assert "empty" in result.lower()

    def test_bind_sets_agent_id(self, tmp_path: Path):
        tk = NotepadToolkit(path=tmp_path)
        tk.bind("agent-x")
        tk.write_notepad("Bound write")
        content = tk.manager.read("agent-x")
        assert "Bound write" in content

    def test_auto_generates_id_if_unbound(self, tmp_path: Path):
        tk = NotepadToolkit(path=tmp_path)
        tk.write_notepad("Auto ID test")
        result = tk.read_notepad()
        assert "Auto ID test" in result
        assert tk._agent_id.startswith("agent-")

    def test_no_args_works(self):
        tk = NotepadToolkit()
        assert tk.preset.name == "default"
        assert tk.manager is not None

    def test_shared_manager(self, tmp_path: Path):
        mgr = NotepadManager(tmp_path)
        tk = NotepadToolkit(manager=mgr)
        tk.bind("test-agent")
        tk.write_notepad("shared manager test")
        assert "shared manager test" in mgr.read("test-agent")


class TestPreset:
    def test_default_preset(self):
        p = Preset.default()
        assert p.name == "default"
        assert "notepad" in p.instructions.lower()

    def test_journal_preset(self):
        p = Preset.journal()
        assert p.name == "journal"
        assert "journal" in p.instructions.lower()

    def test_evolution_preset(self):
        p = Preset.evolution()
        assert p.name == "evolution"
        assert "growth" in p.instructions.lower()

    def test_tool_requests_preset(self):
        p = Preset.tool_requests()
        assert p.name == "tool_requests"
        assert "wish" in p.instructions.lower()

    def test_custom_preset(self):
        p = Preset.custom(instructions="Write only haiku.")
        assert p.name == "custom"
        assert p.instructions == "Write only haiku."

    def test_toolkit_with_preset(self, tmp_path: Path):
        tk = NotepadToolkit(preset=Preset.journal(), path=tmp_path)
        assert tk.preset.name == "journal"
        assert "journal" in tk.instructions.lower()

    def test_toolkit_default_preset(self, tmp_path: Path):
        tk = NotepadToolkit(path=tmp_path)
        assert tk.preset.name == "default"

    def test_repr(self):
        p = Preset.journal()
        assert "journal" in repr(p)
