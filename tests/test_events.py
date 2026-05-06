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
            await log.append(HiveEvent(
                event_type=EventType.TASK_STARTED,
                agent_id="agent-1",
                session_id=sid,
                data={},
            ))
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
