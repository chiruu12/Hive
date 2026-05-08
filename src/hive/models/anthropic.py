"""Anthropic SDK provider — Claude models via direct API."""

import logging
import time

import anthropic

from hive.models.protocol import ModelResponse

logger = logging.getLogger(__name__)


class AnthropicProvider:
    """ModelProvider using the Anthropic SDK."""

    def __init__(self, model: str = "claude-haiku-4-5", api_key: str | None = None):
        from hive.config import get_env

        key = api_key or get_env("ANTHROPIC_API_KEY")
        self._client = anthropic.AsyncAnthropic(api_key=key or "sk-placeholder")
        self._model = model
        self._has_key = bool(key)

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def available(self) -> bool:
        if not self._has_key:
            from hive.config import get_env

            return bool(get_env("ANTHROPIC_API_KEY"))
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

        response = await self._client.messages.create(
            model=self._model,
            system=system or "You are a helpful assistant.",
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        duration_ms = int((time.time() - t0) * 1000)
        content = ""
        for block in response.content:
            if block.type == "text":
                content += block.text

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = _estimate_cost(self._model, input_tokens, output_tokens)

        return ModelResponse(
            content=content,
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=response.stop_reason,
            cost_usd=cost,
            duration_ms=duration_ms,
        )

    async def plan(
        self,
        objective: str,
        available_tools: list[str],
        context: str | None = None,
    ) -> list[dict]:
        tools_str = ", ".join(available_tools) if available_tools else "none"
        prompt = f"Task: {objective}\nAvailable tools: {tools_str}\n"
        if context:
            prompt += f"Context: {context}\n"
        prompt += (
            "\nRespond with ONLY a JSON array of steps. Each step:\n"
            '{"tool": "tool_name", "params": {...}, "rationale": "why"}\n'
        )
        response = await self.complete(
            messages=[{"role": "user", "content": prompt}],
            system="Output only valid JSON. No markdown.",
        )
        import json

        try:
            return json.loads(response.content.strip())
        except (json.JSONDecodeError, ValueError):
            return []


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    from hive.models.registry import get_model_registry

    rates = get_model_registry().cost_per_1k(model)
    return (input_tokens / 1000 * rates["input"]) + (output_tokens / 1000 * rates["output"])
