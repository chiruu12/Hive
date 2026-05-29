"""Tests for provider streaming generation (A2)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from hive.models.anthropic import Anthropic
from hive.models.base import BaseProvider, Capability
from hive.models.groq import Groq
from hive.models.openai import OpenAI
from hive.runtime.types import GenerateResult, Message, StreamEventType


class _PlainProvider(BaseProvider):
    """Provider with no streaming override -- exercises the base default."""

    @property
    def available(self) -> bool:
        return True

    async def generate_with_metadata(self, *args: Any, **kwargs: Any) -> GenerateResult:
        return GenerateResult(
            message=Message.assistant("hello world"),
            model="plain",
            input_tokens=3,
            output_tokens=2,
        )

    async def generate_structured(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError


async def _collect(stream: Any) -> list[Any]:
    return [event async for event in stream]


class TestBaseDefaultStream:
    @pytest.mark.asyncio
    async def test_default_emits_full_text_then_done(self) -> None:
        events = await _collect(_PlainProvider("plain").generate_stream([Message.user("hi")]))

        assert events[0].type == StreamEventType.TEXT
        assert events[0].text == "hello world"
        assert events[-1].type == StreamEventType.DONE
        assert events[-1].result is not None
        assert events[-1].result.message.content == "hello world"

    def test_base_does_not_advertise_streaming(self) -> None:
        assert not _PlainProvider("plain").supports(Capability.STREAMING)


class TestCapabilityFlags:
    def test_anthropic_supports_streaming(self) -> None:
        with patch("hive.models.anthropic.get_env", return_value="sk-test"):
            assert Anthropic.lite().supports(Capability.STREAMING)

    def test_openai_supports_streaming(self) -> None:
        assert OpenAI(api_key="sk-test").supports(Capability.STREAMING)

    def test_openai_compatible_inherits_streaming(self) -> None:
        with patch("hive.models.groq.get_env", return_value="gsk-test"):
            assert Groq().supports(Capability.STREAMING)


def _chunk(content: str | None = None, tool_calls: Any = None, usage: Any = None) -> Any:
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choices = [] if (content is None and tool_calls is None) else [SimpleNamespace(delta=delta)]
    return SimpleNamespace(choices=choices, usage=usage)


class TestOpenAIStream:
    @pytest.mark.asyncio
    async def test_text_deltas_and_final_result(self) -> None:
        p = OpenAI(api_key="sk-test")
        chunks = [
            _chunk(content="Hel"),
            _chunk(content="lo"),
            _chunk(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5)),
        ]

        async def fake_create(**kwargs: Any) -> Any:
            assert kwargs["stream"] is True

            async def gen() -> Any:
                for c in chunks:
                    yield c

            return gen()

        p._client.chat.completions.create = fake_create
        events = await _collect(p.generate_stream([Message.user("hi")]))

        texts = [e.text for e in events if e.type == StreamEventType.TEXT]
        assert texts == ["Hel", "lo"]
        done = events[-1]
        assert done.type == StreamEventType.DONE
        assert done.result.message.content == "Hello"
        assert done.result.input_tokens == 10
        assert done.result.output_tokens == 5

    @pytest.mark.asyncio
    async def test_tool_call_fragments_are_assembled(self) -> None:
        p = OpenAI(api_key="sk-test")
        tc_a = SimpleNamespace(
            index=0, id="call_1", function=SimpleNamespace(name="add", arguments='{"a":')
        )
        tc_b = SimpleNamespace(
            index=0, id=None, function=SimpleNamespace(name=None, arguments=' 1, "b": 2}')
        )
        chunks = [_chunk(tool_calls=[tc_a]), _chunk(tool_calls=[tc_b])]

        async def fake_create(**kwargs: Any) -> Any:
            async def gen() -> Any:
                for c in chunks:
                    yield c

            return gen()

        p._client.chat.completions.create = fake_create
        events = await _collect(p.generate_stream([Message.user("hi")]))

        msg = events[-1].result.message
        assert len(msg.tool_calls) == 1
        call = msg.tool_calls[0]
        assert call.id == "call_1"
        assert call.name == "add"
        assert call.arguments == {"a": 1, "b": 2}


class _FakeAnthropicStreamCM:
    def __init__(self, deltas: list[str], final: Any) -> None:
        self._deltas = deltas
        self._final = final

    async def __aenter__(self) -> Any:
        async def text_stream() -> Any:
            for d in self._deltas:
                yield d

        async def get_final_message() -> Any:
            return self._final

        return SimpleNamespace(text_stream=text_stream(), get_final_message=get_final_message)

    async def __aexit__(self, *args: Any) -> None:
        return None


class TestAnthropicStream:
    @pytest.mark.asyncio
    async def test_text_deltas_and_final_message(self) -> None:
        with patch("hive.models.anthropic.get_env", return_value="sk-test"):
            p = Anthropic.lite()

        final = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="Hello world")],
            usage=SimpleNamespace(input_tokens=12, output_tokens=4),
        )
        p._client.messages.stream = lambda **kw: _FakeAnthropicStreamCM(["Hello ", "world"], final)

        events = await _collect(p.generate_stream([Message.user("hi")]))

        texts = [e.text for e in events if e.type == StreamEventType.TEXT]
        assert texts == ["Hello ", "world"]
        done = events[-1]
        assert done.type == StreamEventType.DONE
        assert done.result.message.content == "Hello world"
        assert done.result.input_tokens == 12
        assert done.result.output_tokens == 4
