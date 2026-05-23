"""Tests for IntentRouter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from hive.routing.router import IntentResult, IntentRouter
from hive.runtime.types import GenerateResult, Message


def _mock_provider(response_text: str) -> MagicMock:
    provider = MagicMock()
    msg = Message.assistant(response_text)
    result = GenerateResult(message=msg, input_tokens=10, output_tokens=5)
    provider.generate = AsyncMock(return_value=msg)
    provider.generate_with_metadata = AsyncMock(return_value=result)
    return provider


INTENTS = {
    "task": "user wants to create a todo item",
    "note": "user wants to save information",
    "query": "user is asking a question",
    "agent": "user needs multi-step help",
}


class TestIntentResult:
    def test_fields(self) -> None:
        r = IntentResult(intent="task", confidence=0.9, raw_text="add a todo")
        assert r.intent == "task"
        assert r.confidence == 0.9
        assert r.raw_text == "add a todo"


class TestIntentRouter:
    @pytest.mark.asyncio
    async def test_classify_json_response(self) -> None:
        provider = _mock_provider('{"intent": "task", "confidence": 0.95}')
        router = IntentRouter(model=provider, intents=INTENTS)

        result = await router.classify("add a todo for tomorrow")

        assert result.intent == "task"
        assert result.confidence == 0.95
        assert result.raw_text == "add a todo for tomorrow"

    @pytest.mark.asyncio
    async def test_classify_json_with_surrounding_text(self) -> None:
        provider = _mock_provider('Sure! {"intent": "query", "confidence": 0.8} is my answer.')
        router = IntentRouter(model=provider, intents=INTENTS)

        result = await router.classify("what is python?")

        assert result.intent == "query"
        assert result.confidence == 0.8

    @pytest.mark.asyncio
    async def test_fallback_on_bad_json(self) -> None:
        provider = _mock_provider("I'm not sure what you mean")
        router = IntentRouter(model=provider, intents=INTENTS, fallback="query")

        result = await router.classify("hello there")

        assert result.intent == "query"
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_fallback_defaults_to_first_intent(self) -> None:
        provider = _mock_provider("garbage response")
        router = IntentRouter(model=provider, intents=INTENTS)

        result = await router.classify("xyz")

        assert result.intent == "task"
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_fuzzy_match_on_name_in_response(self) -> None:
        provider = _mock_provider("The user wants a note saved")
        router = IntentRouter(model=provider, intents=INTENTS)

        result = await router.classify("remember this for me")

        assert result.intent == "note"
        assert result.confidence == 0.5

    @pytest.mark.asyncio
    async def test_unknown_intent_in_json_falls_back(self) -> None:
        provider = _mock_provider('{"intent": "unknown_thing", "confidence": 0.9}')
        router = IntentRouter(model=provider, intents=INTENTS)

        result = await router.classify("do something weird")

        assert result.intent == "task"
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_confidence_clamped(self) -> None:
        provider = _mock_provider('{"intent": "agent", "confidence": 1.5}')
        router = IntentRouter(model=provider, intents=INTENTS)

        result = await router.classify("help me with this project")

        assert result.intent == "agent"
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_negative_confidence_clamped(self) -> None:
        provider = _mock_provider('{"intent": "note", "confidence": -0.5}')
        router = IntentRouter(model=provider, intents=INTENTS)

        result = await router.classify("save this")

        assert result.intent == "note"
        assert result.confidence == 0.0
