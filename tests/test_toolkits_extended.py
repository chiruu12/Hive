"""Tests for WorldToolkit and CommsToolkit."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hive.tools.comms.toolkit import CommsToolkit
from hive.tools.world.toolkit import WorldToolkit

# ---------------------------------------------------------------------------
# WorldToolkit
# ---------------------------------------------------------------------------


class TestWorldToolkit:
    def _make_toolkit(self) -> tuple[WorldToolkit, MagicMock]:
        world = MagicMock()
        world.work.return_value = "Earned $50"
        world.apply_job.return_value = "Hired as Developer"
        world.quit_job.return_value = "Quit your job"
        world.learn.return_value = "Learned Python"
        world.gamble.return_value = MagicMock(description="You won $20!")
        world.get_status.return_value = "Status: doing well"
        world.get_market_summary.return_value = "Market: 3 jobs available"

        from pydantic import BaseModel

        class FakeFinances(BaseModel):
            balance: float = 500.0
            total_earned: float = 600.0
            total_spent: float = 100.0

        class FakeJob(BaseModel):
            title: str = "Developer"
            salary: float = 50.0
            required_skills: list[str] = ["python"]

        world.get_finances.return_value = FakeFinances()
        world.available_jobs.return_value = [FakeJob()]
        world.get_skills.return_value = [MagicMock(skill_name="python", level=0.8)]

        tk = WorldToolkit(world, "agent-1")
        tk.bind("agent-1")
        return tk, world

    @pytest.mark.asyncio
    async def test_work(self):
        tk, world = self._make_toolkit()
        tools = {t.name: t for t in tk.get_tools()}
        result = await tools["work"].call()
        assert result == "Earned $50"
        world.work.assert_called_with("agent-1")

    @pytest.mark.asyncio
    async def test_apply_job(self):
        tk, world = self._make_toolkit()
        tools = {t.name: t for t in tk.get_tools()}
        result = await tools["apply_job"].call(job_id="dev-1")
        assert result == "Hired as Developer"
        world.apply_job.assert_called_with("agent-1", "dev-1")

    @pytest.mark.asyncio
    async def test_quit_job(self):
        tk, world = self._make_toolkit()
        tools = {t.name: t for t in tk.get_tools()}
        result = await tools["quit_job"].call()
        assert result == "Quit your job"

    @pytest.mark.asyncio
    async def test_learn(self):
        tk, world = self._make_toolkit()
        tools = {t.name: t for t in tk.get_tools()}
        result = await tools["learn"].call(skill_name="python")
        assert result == "Learned Python"
        world.learn.assert_called_with("agent-1", "python")

    @pytest.mark.asyncio
    async def test_gamble(self):
        tk, world = self._make_toolkit()
        tools = {t.name: t for t in tk.get_tools()}
        result = await tools["gamble"].call(game="blackjack", wager=20.0)
        assert result == "You won $20!"
        world.gamble.assert_called_with("agent-1", "blackjack", 20.0)

    @pytest.mark.asyncio
    async def test_query_world_status(self):
        tk, world = self._make_toolkit()
        tools = {t.name: t for t in tk.get_tools()}
        result = await tools["query_world"].call(query_type="status")
        assert result == "Status: doing well"

    @pytest.mark.asyncio
    async def test_query_world_market(self):
        tk, world = self._make_toolkit()
        tools = {t.name: t for t in tk.get_tools()}
        result = await tools["query_world"].call(query_type="market")
        assert "3 jobs available" in result

    @pytest.mark.asyncio
    async def test_query_world_finances(self):
        tk, world = self._make_toolkit()
        tools = {t.name: t for t in tk.get_tools()}
        result = await tools["query_world"].call(query_type="finances")
        assert "$500" in result
        assert "$600" in result

    @pytest.mark.asyncio
    async def test_query_world_jobs(self):
        tk, world = self._make_toolkit()
        tools = {t.name: t for t in tk.get_tools()}
        result = await tools["query_world"].call(query_type="jobs")
        assert "Developer" in result
        assert "$50" in result

    @pytest.mark.asyncio
    async def test_query_world_skills(self):
        tk, world = self._make_toolkit()
        tools = {t.name: t for t in tk.get_tools()}
        result = await tools["query_world"].call(query_type="skills")
        assert "python" in result

    @pytest.mark.asyncio
    async def test_query_world_no_jobs(self):
        tk, world = self._make_toolkit()
        world.available_jobs.return_value = []
        tools = {t.name: t for t in tk.get_tools()}
        result = await tools["query_world"].call(query_type="jobs")
        assert result == "No jobs available."

    @pytest.mark.asyncio
    async def test_query_world_no_skills(self):
        tk, world = self._make_toolkit()
        world.get_skills.return_value = []
        tools = {t.name: t for t in tk.get_tools()}
        result = await tools["query_world"].call(query_type="skills")
        assert result == "No skills learned yet."

    def test_tool_discovery(self):
        tk, _ = self._make_toolkit()
        tools = tk.get_tools()
        names = {t.name for t in tools}
        assert names == {"work", "apply_job", "quit_job", "learn", "gamble", "query_world"}


# ---------------------------------------------------------------------------
# CommsToolkit
# ---------------------------------------------------------------------------


class TestCommsToolkit:
    @pytest.mark.asyncio
    async def test_send_and_read(self, tmp_path: Path):
        tk = CommsToolkit(path=tmp_path)
        tk.bind("sender-1")

        tk2 = CommsToolkit(path=tmp_path)
        tk2.bind("receiver-1")

        # Send from sender to receiver
        tools_sender = {t.name: t for t in tk.get_tools()}
        result = await tools_sender["send_message"].call(target_agent="receiver-1", message="hello")
        assert "Sent to receiver-1" in result

        # Read receiver's inbox
        tools_receiver = {t.name: t for t in tk2.get_tools()}
        inbox = await tools_receiver["read_inbox"].call()
        assert "hello" in inbox
        assert "sender-1" in inbox

    @pytest.mark.asyncio
    async def test_empty_inbox(self, tmp_path: Path):
        tk = CommsToolkit(path=tmp_path)
        tk.bind("agent-1")
        tools = {t.name: t for t in tk.get_tools()}
        result = await tools["read_inbox"].call()
        assert result == "No messages."

    @pytest.mark.asyncio
    async def test_multiple_messages(self, tmp_path: Path):
        tk = CommsToolkit(path=tmp_path)
        tk.bind("receiver")

        sender = CommsToolkit(path=tmp_path)
        sender.bind("sender")

        tools_sender = {t.name: t for t in sender.get_tools()}
        await tools_sender["send_message"].call(target_agent="receiver", message="first")
        await tools_sender["send_message"].call(target_agent="receiver", message="second")

        tools = {t.name: t for t in tk.get_tools()}
        inbox = await tools["read_inbox"].call()
        assert "first" in inbox
        assert "second" in inbox
        # Order preserved
        assert inbox.index("first") < inbox.index("second")

    @pytest.mark.asyncio
    async def test_corrupt_jsonl_skipped(self, tmp_path: Path):
        tk = CommsToolkit(path=tmp_path)
        tk.bind("agent-1")

        # Write corrupt line directly
        inbox = tmp_path / "agent-1_inbox.jsonl"
        inbox.write_text(
            "not valid json\n" + json.dumps({"from": "bob", "message": "hi", "ts": "now"}) + "\n"
        )

        tools = {t.name: t for t in tk.get_tools()}
        result = await tools["read_inbox"].call()
        assert "hi" in result
        assert "not valid json" not in result

    @pytest.mark.asyncio
    async def test_auto_generated_id(self, tmp_path: Path):
        tk = CommsToolkit(path=tmp_path)
        # Don't bind — _ensure_id() should auto-generate
        tools = {t.name: t for t in tk.get_tools()}
        result = await tools["send_message"].call(target_agent="someone", message="msg")
        assert "Sent to someone" in result

    def test_tool_discovery(self, tmp_path: Path):
        tk = CommsToolkit(path=tmp_path)
        tools = tk.get_tools()
        names = {t.name for t in tools}
        assert names == {"send_message", "read_inbox"}
