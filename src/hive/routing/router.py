"""Intent classification router using an LLM."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from hive.models.base import BaseProvider
from hive.runtime.types import Message


@dataclass
class IntentResult:
    intent: str
    confidence: float
    raw_text: str


_SYSTEM_PROMPT = (
    "You are an intent classifier. Given user text and a list of intents, "
    "respond with ONLY a JSON object: {\"intent\": \"<name>\", \"confidence\": <0.0-1.0>}. "
    "No other text."
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
        self._intent_block = "\n".join(
            f"- {name}: {desc}" for name, desc in intents.items()
        )

    async def classify(self, text: str) -> IntentResult:
        prompt = f"Intents:\n{self._intent_block}\n\nUser text: {text}"
        messages = [
            Message.system(_SYSTEM_PROMPT),
            Message.user(prompt),
        ]

        response = await self._model.generate(messages, max_tokens=128)
        raw = response.content.strip()

        return self._parse_response(raw, text)

    def _parse_response(self, raw: str, original_text: str) -> IntentResult:
        try:
            match = re.search(r"\{[^}]+\}", raw)
            if match:
                data = json.loads(match.group())
                intent = data.get("intent", "")
                confidence = float(data.get("confidence", 0.0))
                if intent in self._intents:
                    return IntentResult(
                        intent=intent,
                        confidence=min(max(confidence, 0.0), 1.0),
                        raw_text=original_text,
                    )
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        for name in self._intents:
            if name.lower() in raw.lower():
                return IntentResult(intent=name, confidence=0.5, raw_text=original_text)

        return IntentResult(intent=self._fallback, confidence=0.0, raw_text=original_text)
