"""Fireworks AI provider — fast inference via OpenAI-compatible API."""

import logging
import time

import openai

from hive.models.protocol import ModelResponse

logger = logging.getLogger(__name__)

FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"


class FireworksProvider:
    """ModelProvider using Fireworks AI's OpenAI-compatible endpoint."""

    def __init__(
        self,
        model: str = "accounts/fireworks/models/llama-v3p1-8b-instruct",
        api_key: str | None = None,
    ):
        from hive.config import get_env

        key = api_key or get_env("FIREWORKS_API_KEY")
        self._client = openai.AsyncOpenAI(
            api_key=key or "placeholder",
            base_url=FIREWORKS_BASE_URL,
        )
        self._model = model
        self._has_key = bool(key)

    @property
    def name(self) -> str:
        return "fireworks"

    @property
    def available(self) -> bool:
        if not self._has_key:
            from hive.config import get_env

            return bool(get_env("FIREWORKS_API_KEY"))
        return True

    async def complete(
        self,
        messages: list[dict[str, str]],
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> ModelResponse:
        t0 = time.time()

        msgs: list[dict[str, str]] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        duration_ms = int((time.time() - t0) * 1000)
        choice = response.choices[0]
        content = choice.message.content or ""

        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0

        from hive.models.registry import estimate_cost

        cost = estimate_cost(self._model, input_tokens, output_tokens)

        return ModelResponse(
            content=content,
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=choice.finish_reason,
            cost_usd=cost,
            duration_ms=duration_ms,
        )
