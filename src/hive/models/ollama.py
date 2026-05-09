"""Ollama provider — local models via OpenAI-compatible API."""

import logging
import time

import httpx

from hive.models.protocol import ModelResponse

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:11434"


class OllamaProvider:
    """ModelProvider using Ollama's OpenAI-compatible endpoint."""

    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str = DEFAULT_BASE_URL,
    ):
        self._model = model
        self._base_url = base_url.rstrip("/")

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def available(self) -> bool:
        try:
            resp = httpx.get(f"{self._base_url}/api/tags", timeout=2)
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

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

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self._base_url}/v1/chat/completions",
                json={
                    "model": self._model,
                    "messages": msgs,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "stream": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        duration_ms = int((time.time() - t0) * 1000)
        choice = data.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "")

        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        return ModelResponse(
            content=content,
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=choice.get("finish_reason"),
            cost_usd=0.0,
            duration_ms=duration_ms,
        )
