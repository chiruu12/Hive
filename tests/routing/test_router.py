"""Tests for IntentRouter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from hive.routing.router import IntentClassification, IntentResult, IntentRouter
from hive.runtime.types import Message


def _mock_structured_provider(intent: str, confidence: float) -> MagicMock:
    """Mock that returns structured output via generate_structured."""
    provider = MagicMock()
    classification = IntentClassification(intent=intent, confidence=confidence)
    provider.generate_structured = AsyncMock(return_value=classification)
    provider.generate = AsyncMock(
        return_value=Message.assistant(f'{{"intent": "{intent}", "confidence": {confidence}}}')
    )
    return provider


def _mock_text_provider(response_text: str) -> MagicMock:
    """Mock that fails structured output, falls back to text."""
    provider = MagicMock()
    provider.generate_structured = AsyncMock(side_effect=Exception("not supported"))
    provider.generate = AsyncMock(return_value=Message.assistant(response_text))
    return provider


INTENTS = {
    "task": "user wants to create a todo item",
    "note": "user wants to save information",
    "query": "user is asking a question",
    "agent": "user needs multi-step help",
}


class TestIntentClassification:
    def test_validation(self) -> None:
        ic = IntentClassification(intent="task", confidence=0.95)
        assert ic.intent == "task"
        assert ic.confidence == 0.95

    def test_confidence_bounds(self) -> None:
        ic = IntentClassification(intent="task", confidence=0.0)
        assert ic.confidence == 0.0
        ic2 = IntentClassification(intent="task", confidence=1.0)
        assert ic2.confidence == 1.0

    def test_rejects_invalid_confidence(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            IntentClassification(intent="task", confidence=1.5)
        with pytest.raises(ValidationError):
            IntentClassification(intent="task", confidence=-0.1)


class TestIntentResult:
    def test_fields(self) -> None:
        r = IntentResult(intent="task", confidence=0.9, raw_text="add a todo")
        assert r.intent == "task"
        assert r.confidence == 0.9
        assert r.raw_text == "add a todo"

    def test_pydantic_model(self) -> None:
        r = IntentResult(intent="note", confidence=0.5, raw_text="save this")
        d = r.model_dump()
        assert d["intent"] == "note"
        assert d["confidence"] == 0.5


class TestIntentRouter:
    @pytest.mark.asyncio
    async def test_structured_classification(self) -> None:
        provider = _mock_structured_provider("task", 0.95)
        router = IntentRouter(model=provider, intents=INTENTS)

        result = await router.classify("add a todo for tomorrow")

        assert result.intent == "task"
        assert result.confidence == 0.95
        assert result.raw_text == "add a todo for tomorrow"
        provider.generate_structured.assert_called_once()

    @pytest.mark.asyncio
    async def test_structured_unknown_intent_falls_back(self) -> None:
        provider = _mock_structured_provider("dance", 0.9)
        router = IntentRouter(model=provider, intents=INTENTS)

        result = await router.classify("let's dance")

        assert result.intent == "task"
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_text_fallback_on_structured_failure(self) -> None:
        provider = _mock_text_provider("The user wants a note saved")
        router = IntentRouter(model=provider, intents=INTENTS)

        result = await router.classify("remember this for me")

        assert result.intent == "note"
        assert result.confidence == 0.5

    @pytest.mark.asyncio
    async def test_text_fallback_garbage(self) -> None:
        provider = _mock_text_provider("I don't understand")
        router = IntentRouter(model=provider, intents=INTENTS, fallback="query")

        result = await router.classify("asdfgh")

        assert result.intent == "query"
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_fallback_defaults_to_first_intent(self) -> None:
        provider = _mock_text_provider("gibberish")
        router = IntentRouter(model=provider, intents=INTENTS)

        result = await router.classify("xyz")

        assert result.intent == "task"
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_structured_with_wrapped_result(self) -> None:
        """Test when generate_structured returns a wrapper with .parsed."""
        provider = MagicMock()
        wrapper = MagicMock()
        wrapper.parsed = IntentClassification(intent="query", confidence=0.8)
        provider.generate_structured = AsyncMock(return_value=wrapper)

        router = IntentRouter(model=provider, intents=INTENTS)
        result = await router.classify("what is python?")

        assert result.intent == "query"
        assert result.confidence == 0.8
