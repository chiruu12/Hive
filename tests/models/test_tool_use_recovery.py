"""Tests for no-tools tool-call recovery (provider tool_use_failed handling).

When a no-tools request triggers a provider's ``tool_use_failed`` rejection (the model
called a tool when none were offered, which strict providers like Groq 400 on), the
OpenAI-compatible adapter retries once with a text-only instruction and falls back to
clean text rather than surfacing the error -- the tools already ran, so the turn must
still complete.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from hive.models.openai import _TEXT_ONLY_NUDGE, OpenAI, _is_tool_use_failed
from hive.runtime.types import Message, StreamEventType


class _ToolUseFailedError(Exception):
    """Mimics Groq's strict ``tool_use_failed`` 400 on a no-tools request."""

    def __init__(self) -> None:
        super().__init__("Tool choice is none, but model called a tool")
        self.status_code = 400  # so _retry_with_backoff treats it as non-retryable
        self.code = "tool_use_failed"
        self.body = {
            "error": {"code": "tool_use_failed", "type": "invalid_request_error"},
        }


def _response(text: str, prompt_tokens: int = 7, completion_tokens: int = 4) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


def _has_nudge(messages: list[dict[str, Any]]) -> bool:
    return any(m.get("role") == "system" and m.get("content") == _TEXT_ONLY_NUDGE for m in messages)


def _stream_chunk(content: str | None = None, usage: Any = None) -> Any:
    delta = SimpleNamespace(content=content, tool_calls=None)
    choices = [] if content is None else [SimpleNamespace(delta=delta)]
    return SimpleNamespace(choices=choices, usage=usage)


async def _collect(stream: Any) -> list[Any]:
    return [event async for event in stream]


class TestDetector:
    def test_matches_code_attribute(self) -> None:
        assert _is_tool_use_failed(_ToolUseFailedError())

    def test_matches_body_error_code(self) -> None:
        err = Exception("nope")
        err.body = {"error": {"code": "tool_use_failed"}}  # type: ignore[attr-defined]
        assert _is_tool_use_failed(err)

    def test_matches_message_text(self) -> None:
        assert _is_tool_use_failed(Exception("the model called a tool unexpectedly"))

    def test_unrelated_400_does_not_match(self) -> None:
        err = Exception("invalid request: bad parameter")
        err.code = "invalid_request_error"  # type: ignore[attr-defined]
        assert not _is_tool_use_failed(err)


class TestGenerateWithMetadataRecovery:
    @pytest.mark.asyncio
    async def test_recovers_with_text_only_retry(self) -> None:
        p = OpenAI(api_key="sk-test")
        calls: list[dict[str, Any]] = []

        async def fake_create(**kwargs: Any) -> Any:
            calls.append(kwargs)
            if not _has_nudge(kwargs["messages"]):
                raise _ToolUseFailedError()
            return _response("Saved three notes.")

        p._client.chat.completions.create = fake_create
        result = await p.generate_with_metadata([Message.user("make three notes")], None)

        assert result.message.content == "Saved three notes."
        assert result.message.tool_calls == ()
        assert len(calls) == 2  # initial no-tools call + one recovery retry
        assert _has_nudge(calls[1]["messages"])

    @pytest.mark.asyncio
    async def test_second_failure_falls_back_to_empty_text(self) -> None:
        p = OpenAI(api_key="sk-test")

        async def fake_create(**kwargs: Any) -> Any:
            raise _ToolUseFailedError()

        p._client.chat.completions.create = fake_create
        result = await p.generate_with_metadata([Message.user("make three notes")], None)

        assert result.message.content == ""
        assert result.message.tool_calls == ()

    @pytest.mark.asyncio
    async def test_unrelated_error_still_raises(self) -> None:
        p = OpenAI(api_key="sk-test")

        async def fake_create(**kwargs: Any) -> Any:
            raise ValueError("boom")

        p._client.chat.completions.create = fake_create
        with pytest.raises(ValueError, match="boom"):
            await p.generate_with_metadata([Message.user("hi")], None)


class TestGenerateStreamRecovery:
    @pytest.mark.asyncio
    async def test_recovers_with_text_only_retry(self) -> None:
        p = OpenAI(api_key="sk-test")
        calls: list[dict[str, Any]] = []

        async def fake_create(**kwargs: Any) -> Any:
            calls.append(kwargs)
            if not _has_nudge(kwargs["messages"]):
                raise _ToolUseFailedError()

            async def gen() -> Any:
                yield _stream_chunk(content="Saved ")
                yield _stream_chunk(content="three notes.")
                yield _stream_chunk(usage=SimpleNamespace(prompt_tokens=7, completion_tokens=4))

            return gen()

        p._client.chat.completions.create = fake_create
        events = await _collect(p.generate_stream([Message.user("make three notes")], None))

        texts = [e.text for e in events if e.type == StreamEventType.TEXT]
        assert texts == ["Saved ", "three notes."]
        done = events[-1]
        assert done.type == StreamEventType.DONE
        assert done.result.message.content == "Saved three notes."
        assert len(calls) == 2
        assert _has_nudge(calls[1]["messages"])

    @pytest.mark.asyncio
    async def test_second_failure_falls_back_to_empty_done(self) -> None:
        p = OpenAI(api_key="sk-test")

        async def fake_create(**kwargs: Any) -> Any:
            raise _ToolUseFailedError()

        p._client.chat.completions.create = fake_create
        events = await _collect(p.generate_stream([Message.user("make three notes")], None))

        assert [e.type for e in events if e.type == StreamEventType.TEXT] == []
        done = events[-1]
        assert done.type == StreamEventType.DONE
        assert done.result.message.content == ""
