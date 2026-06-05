"""Tests for the SSE streaming bridge, incl. the guardrail-leak fix."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import hive.server.streaming as streaming
from hive.config import HiveConfig
from hive.runtime.types import TaskResult, TaskStatus


class _FakeAgent:
    """Pushes a raw (unredacted) token via on_text, returns a redacted result."""

    def __init__(self, on_text: Any) -> None:
        self._on_text = on_text

    async def run(self, task: Any) -> TaskResult:
        if self._on_text is not None:
            self._on_text("contact leak@corp.com")  # raw delta
        return TaskResult(
            task_id="t", status=TaskStatus.COMPLETED, output="contact [REDACTED:email]"
        )


def _patch_build(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]) -> None:
    def fake_build(ctx: Any, agent: Any, session_id: str, on_text: Any = None) -> _FakeAgent:
        captured["on_text"] = on_text
        return _FakeAgent(on_text)

    monkeypatch.setattr("hive.server.runner.build_oneshot_agent", fake_build)


async def _collect(ctx: Any) -> list[dict[str, str]]:
    return [e async for e in streaming.stream_task(ctx, None, "hi", "sess", 5)]


@pytest.mark.asyncio
async def test_tokens_suppressed_when_guardrails_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    _patch_build(monkeypatch, captured)
    cfg = HiveConfig()
    cfg.guardrails.enabled = True
    events = await _collect(SimpleNamespace(config=cfg))

    assert captured["on_text"] is None  # no raw token deltas forwarded
    assert [e for e in events if e["event"] == "token"] == []
    # An up-front info event signals the intentional suppression to the client.
    assert events[0]["event"] == "info" and "suppressed" in events[0]["data"]
    done = next(e for e in events if e["event"] == "done")
    assert "leak@corp.com" not in done["data"]  # only the redacted final output


@pytest.mark.asyncio
async def test_tokens_streamed_when_guardrails_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    _patch_build(monkeypatch, captured)
    cfg = HiveConfig()
    cfg.guardrails.enabled = False
    events = await _collect(SimpleNamespace(config=cfg))

    assert captured["on_text"] is not None  # streaming preserved when no guardrails
    assert any(e["event"] == "token" for e in events)
    assert not any(e["event"] == "info" for e in events)  # no suppression notice
