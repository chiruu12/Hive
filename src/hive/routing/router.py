"""Intent classification router using an LLM with structured output."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from hive.models.base import BaseProvider
from hive.runtime.types import Message

logger = logging.getLogger(__name__)


class IntentClassification(BaseModel):
    """Structured output model for intent classification."""

    intent: str = Field(description="The matched intent name")
    confidence: float = Field(ge=0.0, le=1.0, description="Classification confidence 0.0-1.0")


class IntentResult(BaseModel):
    """Result of classifying user text into an intent."""

    intent: str
    confidence: float = Field(ge=0.0, le=1.0)
    raw_text: str


_SYSTEM_PROMPT = (
    "You are an intent classifier. Given user text and a list of intents, "
    "classify the text into exactly one intent. Respond with the intent name "
    "and your confidence (0.0 to 1.0)."
)


class IntentRouter:
    """Classify user text into one of a set of intents using an LLM."""

    def __init__(
        self,
        model: BaseProvider,
        intents: dict[str, str],
        fallback: str | None = None,
    ) -> None:
        self._model = model
        self._intents = intents
        self._fallback = fallback or next(iter(intents))
        self._intent_block = "\n".join(f"- {name}: {desc}" for name, desc in intents.items())

    async def classify(self, text: str) -> IntentResult:
        try:
            return await self._classify_structured(text)
        except Exception:
            logger.debug("Structured classification failed, falling back to text parsing")
            return await self._classify_text(text)

    async def _classify_structured(self, text: str) -> IntentResult:
        """Try structured output first — provider parses JSON for us."""
        prompt = f"Intents:\n{self._intent_block}\n\nUser text: {text}"
        messages = [Message.system(_SYSTEM_PROMPT), Message.user(prompt)]

        parsed: Any = await self._model.generate_structured(
            messages, output_type=IntentClassification, max_tokens=128
        )

        if isinstance(parsed, IntentClassification):
            classification = parsed
        elif hasattr(parsed, "parsed"):
            classification = parsed.parsed
        else:
            raise ValueError("Unexpected structured output format")

        intent = classification.intent
        if intent not in self._intents:
            return IntentResult(intent=self._fallback, confidence=0.0, raw_text=text)

        return IntentResult(
            intent=intent,
            confidence=classification.confidence,
            raw_text=text,
        )

    async def _classify_text(self, text: str) -> IntentResult:
        """Fallback: parse free-text response."""
        prompt = (
            f"Intents:\n{self._intent_block}\n\nUser text: {text}\n\n"
            "Respond with ONLY the intent name."
        )
        messages = [Message.system(_SYSTEM_PROMPT), Message.user(prompt)]
        response = await self._model.generate(messages, max_tokens=128)
        raw = response.content.strip().lower()

        for name in self._intents:
            if name.lower() in raw:
                return IntentResult(intent=name, confidence=0.5, raw_text=text)

        return IntentResult(intent=self._fallback, confidence=0.0, raw_text=text)
