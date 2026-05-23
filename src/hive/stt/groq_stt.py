"""Groq Whisper API STT provider."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

import httpx
from pydantic import BaseModel

from hive.stt.base import TranscriptionResult

logger = logging.getLogger(__name__)

_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_MODEL = "whisper-large-v3-turbo"
_MAX_RETRIES = 3
_BASE_DELAY = 1.0
_RETRYABLE = {429, 500, 502, 503}


class _GroqResponse(BaseModel):
    text: str = ""
    language: str = ""
    duration: float = 0.0


class GroqSTT:
    """Speech-to-text via Groq's hosted Whisper API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = _MODEL,
        timeout: float = 60.0,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        self._api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    @property
    def available(self) -> bool:
        return self._api_key != ""

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        client = await self._get_client()
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                with open(audio_path, "rb") as f:
                    resp = await client.post(
                        _API_URL,
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        files={"file": (audio_path.name, f, "audio/wav")},
                        data={"model": self._model, "response_format": "verbose_json"},
                    )

                if resp.status_code in _RETRYABLE and attempt < self._max_retries:
                    delay = _BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "Groq STT %d (attempt %d/%d, retry in %.1fs)",
                        resp.status_code, attempt + 1, self._max_retries + 1, delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                resp.raise_for_status()
                parsed = _GroqResponse.model_validate(resp.json())
                return TranscriptionResult(
                    text=parsed.text.strip(),
                    language=parsed.language,
                    duration_ms=int(parsed.duration * 1000),
                    provider="groq",
                )
            except httpx.RequestError as e:
                last_error = e
                if attempt < self._max_retries:
                    delay = _BASE_DELAY * (2 ** attempt)
                    logger.warning("Groq STT network error (attempt %d): %s", attempt + 1, e)
                    await asyncio.sleep(delay)
                    continue
                raise

        raise last_error or RuntimeError("Groq STT retry exhausted")

    async def transcribe_bytes(
        self, audio: bytes, sample_rate: int = 16000
    ) -> TranscriptionResult:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_path = Path(f.name)
            f.write(audio)

        try:
            return await self.transcribe(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
