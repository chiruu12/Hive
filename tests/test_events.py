"""Tests for event log system."""

import asyncio

from hive.memory.events import EventLog, EventType, HiveEvent


def test_event_serialize_deserialize():
    event = HiveEvent(
        event_type=EventType.GOAL_SET,
        agent_id="agent-1",
        session_id="sess-1",
        data={"goal_id": "g-1", "objective": "test"},
    )
    line = event.to_jsonl()
    restored = HiveEvent.from_jsonl(line)
    assert restored.event_type == EventType.GOAL_SET
    assert restored.data["goal_id"] == "g-1"


def test_append_and_replay(tmp_dir):
    log = EventLog(tmp_dir)

    async def _run():
        e1 = HiveEvent(
            event_type=EventType.GOAL_SET,
            agent_id="agent-1",
            session_id="sess-1",
            data={"goal": "test goal 1"},
        )
        e2 = HiveEvent(
            event_type=EventType.TOOL_USED,
            agent_id="agent-1",
            session_id="sess-1",
            data={"tool": "world_query"},
        )
        await log.append(e1)
        await log.append(e2)

        events = await log.replay("agent-1", "sess-1")
        assert len(events) == 2
        assert events[0].event_type == EventType.GOAL_SET
        assert events[1].event_type == EventType.TOOL_USED

    asyncio.run(_run())


def test_list_sessions(tmp_dir):
    log = EventLog(tmp_dir)

    async def _run():
        for sid in ["sess-a", "sess-b"]:
            await log.append(
                HiveEvent(
                    event_type=EventType.TASK_STARTED,
                    agent_id="agent-1",
                    session_id=sid,
                    data={},
                )
            )
        sessions = await log.list_sessions("agent-1")
        assert "sess-a" in sessions
        assert "sess-b" in sessions

    asyncio.run(_run())


def test_all_event_types_valid():
    for et in EventType:
        event = HiveEvent(
            event_type=et,
            agent_id="test",
            session_id="test",
            data={},
        )
        line = event.to_jsonl()
        restored = HiveEvent.from_jsonl(line)
        assert restored.event_type == et


def test_fsync_append_durable_and_readable(tmp_dir):
    """With fsync enabled, appends still round-trip and the file is on disk."""
    log = EventLog(tmp_dir, fsync=True)

    async def _run():
        await log.append(
            HiveEvent(
                event_type=EventType.GOAL_SET,
                agent_id="agent-1",
                session_id="sess-1",
                data={"goal": "durable"},
            )
        )
        events = await log.replay("agent-1", "sess-1")
        assert len(events) == 1
        assert events[0].data["goal"] == "durable"

    asyncio.run(_run())


def test_replay_tolerates_partial_last_line(tmp_dir):
    """A torn/half-written final line must not break replay of prior events."""
    log = EventLog(tmp_dir)

    async def _run():
        await log.append(
            HiveEvent(
                event_type=EventType.GOAL_SET,
                agent_id="agent-1",
                session_id="sess-1",
                data={"goal": "complete"},
            )
        )
        # Simulate an interrupted append: a partial JSON line with no newline.
        path = log._session_path("agent-1", "sess-1")
        with open(path, "a") as f:
            f.write('{"event_type": "tool_used", "agen')

        events = await log.replay("agent-1", "sess-1")
        assert len(events) == 1
        assert events[0].data["goal"] == "complete"

    asyncio.run(_run())


def test_replay_handles_unicode_line_separators(tmp_dir):
    """A record whose text contains U+2028/U+2029/NEL must not be shredded.

    These are legal (unescaped) inside JSON strings and have no '\\n', so the
    record is one physical line -- but str.splitlines() would break it apart.
    """
    log = EventLog(tmp_dir)

    async def _run():
        tricky = "before middle after\x85end"
        await log.append(
            HiveEvent(
                event_type=EventType.ASSISTANT_MESSAGE,
                agent_id="agent-1",
                session_id="sess-1",
                data={"text": tricky},
            )
        )
        await log.append(
            HiveEvent(
                event_type=EventType.TOOL_USED,
                agent_id="agent-1",
                session_id="sess-1",
                data={"tool": "x"},
            )
        )
        events = await log.replay("agent-1", "sess-1")
        assert len(events) == 2  # not shredded into extra/broken lines
        assert events[0].data["text"] == tricky
        assert events[1].data["tool"] == "x"

    asyncio.run(_run())


def test_replay_raises_on_mid_log_corruption(tmp_dir):
    """A malformed line that is NOT the torn final line is real corruption -- surface it."""
    import pytest

    log = EventLog(tmp_dir)

    async def _run():
        await log.append(
            HiveEvent(
                event_type=EventType.GOAL_SET,
                agent_id="agent-1",
                session_id="sess-1",
                data={"goal": "ok"},
            )
        )
        # A complete (newline-terminated) but corrupt record, then a valid one.
        path = log._session_path("agent-1", "sess-1")
        with open(path, "a") as f:
            f.write("{not valid json}\n")
            f.write(
                HiveEvent(
                    event_type=EventType.TOOL_USED,
                    agent_id="agent-1",
                    session_id="sess-1",
                ).to_jsonl()
                + "\n"
            )
        with pytest.raises(ValueError):
            await log.replay("agent-1", "sess-1")

    asyncio.run(_run())
