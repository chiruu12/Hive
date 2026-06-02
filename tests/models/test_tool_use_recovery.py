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

from hive.models.openai import (
    _TEXT_ONLY_NUDGE,
    OpenAI,
    _is_response_format_unsupported,
    _is_tool_use_failed,
)
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
    return any(m.get("role") == "user" and m.get("content") == _TEXT_ONLY_NUDGE for m in messages)


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


class TestResponseFormatUnsupportedDetector:
    def test_matches_body_param(self) -> None:
        err = Exception("nope")
        err.body = {"error": {"param": "response_format"}}  # type: ignore[attr-defined]
        assert _is_response_format_unsupported(err)

    def test_matches_body_unsupported_code(self) -> None:
        err = Exception("nope")
        err.body = {"error": {"code": "unsupported_parameter"}}  # type: ignore[attr-defined]
        assert _is_response_format_unsupported(err)

    def test_matches_message_substring(self) -> None:
        assert _is_response_format_unsupported(Exception("json_schema not supported here"))

    def test_unrelated_error_does_not_match(self) -> None:
        err = Exception("rate limited")
        err.body = {"error": {"code": "rate_limit_exceeded"}}  # type: ignore[attr-defined]
        assert not _is_response_format_unsupported(err)


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

    @pytest.mark.asyncio
    async def test_tool_use_failed_with_tools_offered_propagates(self) -> None:
        # A tool_use_failed on a request that *did* offer tools is a real error
        # (e.g. malformed schema) -- it must not be swallowed by recovery.
        p = OpenAI(api_key="sk-test")
        calls: list[dict[str, Any]] = []

        async def fake_create(**kwargs: Any) -> Any:
            calls.append(kwargs)
            raise _ToolUseFailedError()

        p._client.chat.completions.create = fake_create
        tools = [{"name": "add", "description": "Add.", "input_schema": {"type": "object"}}]
        with pytest.raises(_ToolUseFailedError):
            await p.generate_with_metadata([Message.user("add")], tools)
        assert len(calls) == 1  # no recovery retry attempted


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

    @pytest.mark.asyncio
    async def test_recovery_stream_error_preserves_streamed_text(self) -> None:
        # Double failure: initial no-tools call rejects, then the recovery stream emits
        # some text and errors mid-flight. The terminal DONE must carry the text already
        # streamed (not empty), so consumers reconstructing from DONE.result don't lose it.
        p = OpenAI(api_key="sk-test")

        async def fake_create(**kwargs: Any) -> Any:
            if not _has_nudge(kwargs["messages"]):
                raise _ToolUseFailedError()

            async def gen() -> Any:
                yield _stream_chunk(content="Saved the ")
                yield _stream_chunk(content="notes")
                raise _ToolUseFailedError()

            return gen()

        p._client.chat.completions.create = fake_create
        events = await _collect(p.generate_stream([Message.user("make three notes")], None))

        texts = [e.text for e in events if e.type == StreamEventType.TEXT]
        assert texts == ["Saved the ", "notes"]
        done = events[-1]
        assert done.type == StreamEventType.DONE
        assert done.result.message.content == "Saved the notes"

    @pytest.mark.asyncio
    async def test_error_after_text_propagates_without_duplicate(self) -> None:
        # If the stream fails *after* text already reached the caller, recovery would
        # duplicate output -- so the error must propagate instead of recovering.
        p = OpenAI(api_key="sk-test")
        calls: list[dict[str, Any]] = []

        async def fake_create(**kwargs: Any) -> Any:
            calls.append(kwargs)

            async def gen() -> Any:
                yield _stream_chunk(content="partial ")
                raise _ToolUseFailedError()

            return gen()

        p._client.chat.completions.create = fake_create
        events: list[Any] = []
        with pytest.raises(_ToolUseFailedError):
            async for event in p.generate_stream([Message.user("make three notes")], None):
                events.append(event)

        assert [e.text for e in events if e.type == StreamEventType.TEXT] == ["partial "]
        assert len(calls) == 1  # no recovery retry after content streamed

    @pytest.mark.asyncio
    async def test_tool_use_failed_with_tools_offered_propagates(self) -> None:
        p = OpenAI(api_key="sk-test")
        calls: list[dict[str, Any]] = []

        async def fake_create(**kwargs: Any) -> Any:
            calls.append(kwargs)
            raise _ToolUseFailedError()

        p._client.chat.completions.create = fake_create
        tools = [{"name": "add", "description": "Add.", "input_schema": {"type": "object"}}]
        with pytest.raises(_ToolUseFailedError):
            async for _ in p.generate_stream([Message.user("add")], tools):
                pass
        assert len(calls) == 1  # no recovery retry attempted
