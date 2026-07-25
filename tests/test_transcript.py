"""Tests for the Transcript recorder."""

from __future__ import annotations

import json
from pathlib import Path

from hive.interactions.base import Message, RoundResult
from hive.interactions.transcript import Transcript


def _round_result(
    round_num: int, messages: list[Message] | None = None, evidence: str = ""
) -> RoundResult:
    return RoundResult(round_num=round_num, messages=messages or [], evidence_revealed=evidence)


def _msg(sender: str, content: str, recipient: str = "all") -> Message:
    return Message(round=0, sender=sender, content=content, recipient=recipient)


class TestTranscript:
    def test_add_round(self):
        t = Transcript()
        rr = _round_result(0, [_msg("alice", "hello")])
        t.add_round(rr)
        assert len(t._rounds) == 1

    def test_save_returns_empty_without_dir(self):
        t = Transcript()
        t.add_round(_round_result(0))
        result = t.save("test_scenario")
        assert result == ""

    def test_save_creates_json_file(self, tmp_path: Path):
        t = Transcript(output_dir=tmp_path)
        t.add_round(_round_result(0, [_msg("alice", "hello"), _msg("bob", "hi")]))
        t.add_round(_round_result(1, [_msg("alice", "what?")]))

        path_str = t.save("my_scenario")
        assert path_str
        path = Path(path_str)
        assert path.exists()
        assert path.suffix == ".json"
        assert "my_scenario" in path.name

    def test_save_json_content(self, tmp_path: Path):
        t = Transcript(output_dir=tmp_path)
        t.add_round(_round_result(0, [_msg("alice", "hello")], evidence="A clue!"))
        t.add_round(_round_result(1, [_msg("bob", "I see")]))

        path_str = t.save("test")
        data = json.loads(Path(path_str).read_text())

        assert data["scenario"] == "test"
        assert data["total_messages"] == 2
        assert len(data["rounds"]) == 2
        assert data["rounds"][0]["evidence_revealed"] == "A clue!"

    def test_save_creates_parent_dirs(self, tmp_path: Path):
        nested = tmp_path / "deep" / "nested" / "dir"
        t = Transcript(output_dir=nested)
        t.add_round(_round_result(0))

        path_str = t.save("test")
        assert Path(path_str).exists()

    def test_render_text_empty(self):
        t = Transcript()
        assert t.render_text() == ""

    def test_render_text_with_messages(self):
        t = Transcript()
        t.add_round(_round_result(0, [_msg("alice", "hello"), _msg("bob", "hi")]))
        t.add_round(_round_result(1, [_msg("alice", "what do you think?")]))

        text = t.render_text()
        assert "--- Round 0 ---" in text
        assert "--- Round 1 ---" in text
        assert "alice: hello" in text
        assert "bob: hi" in text
        assert "what do you think?" in text

    def test_render_text_with_evidence(self):
        t = Transcript()
        t.add_round(_round_result(0, [_msg("alice", "hello")], evidence="The weapon was found"))

        text = t.render_text()
        assert "[EVIDENCE]" in text
        assert "The weapon was found" in text

    def test_render_text_directed_message(self):
        t = Transcript()
        t.add_round(_round_result(0, [_msg("bob", "secret info", recipient="alice")]))

        text = t.render_text()
        assert "bob → alice" in text

    def test_render_text_truncates_long_content(self):
        t = Transcript()
        long_msg = "x" * 500
        t.add_round(_round_result(0, [_msg("alice", long_msg)]))

        text = t.render_text()
        # Content should be truncated to 200 chars
        assert "x" * 201 not in text

    def test_multiple_saves_different_timestamps(self, tmp_path: Path):
        t = Transcript(output_dir=tmp_path)
        t.add_round(_round_result(0))

        path1 = t.save("scenario_a")
        path2 = t.save("scenario_b")
        assert path1 != path2
        assert Path(path1).exists()
        assert Path(path2).exists()
