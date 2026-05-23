"""Deepgram Nova-2 STT provider."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import httpx
from pydantic import BaseModel

from hive.stt.base import TranscriptionResult

logger = logging.getLogger(__name__)

_API_URL = "https://api.deepgram.com/v1/listen"
_MODEL = "nova-2"
_MAX_RETRIES = 3
_BASE_DELAY = 1.0
_RETRYABLE = {429, 500, 502, 503}


class _Alternative(BaseModel):
    transcript: str = ""


class _Channel(BaseModel):
    alternatives: list[_Alternative] = []
    detected_language: str = ""


class _Metadata(BaseModel):
    duration: float = 0.0


class _DeepgramResult(BaseModel):
    channels: list[_Channel] = []
    metadata: _Metadata = _Metadata()


class _DeepgramResponse(BaseModel):
    results: _DeepgramResult = _DeepgramResult()


class DeepgramSTT:
    """Speech-to-text via Deepgram's Nova-2 API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = _MODEL,
        timeout: float = 60.0,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        self._api_key = api_key or os.environ.get("DEEPGRAM_API_KEY", "")
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
        with open(audio_path, "rb") as f:
            audio_data = f.read()
        return await self._transcribe_raw(audio_data)

    async def transcribe_bytes(
        self, audio: bytes, sample_rate: int = 16000
    ) -> TranscriptionResult:
        return await self._transcribe_raw(audio)

    async def _transcribe_raw(self, audio_data: bytes) -> TranscriptionResult:
        client = await self._get_client()
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                resp = await client.post(
                    _API_URL,
                    params={"model": self._model, "detect_language": "true"},
                    headers={
                        "Authorization": f"Token {self._api_key}",
                        "Content-Type": "audio/wav",
                    },
                    content=audio_data,
                )

                if resp.status_code in _RETRYABLE and attempt < self._max_retries:
                    delay = _BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "Deepgram STT %d (attempt %d/%d, retry in %.1fs)",
                        resp.status_code, attempt + 1, self._max_retries + 1, delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                resp.raise_for_status()
                parsed = _DeepgramResponse.model_validate(resp.json())
                channel = parsed.results.channels[0] if parsed.results.channels else _Channel()
                alt = channel.alternatives[0] if channel.alternatives else _Alternative()

                return TranscriptionResult(
                    text=alt.transcript.strip(),
                    language=channel.detected_language,
                    duration_ms=int(parsed.results.metadata.duration * 1000),
                    provider="deepgram",
                )
            except httpx.RequestError as e:
                last_error = e
                if attempt < self._max_retries:
                    delay = _BASE_DELAY * (2 ** attempt)
                    logger.warning("Deepgram STT network error (attempt %d): %s", attempt + 1, e)
                    await asyncio.sleep(delay)
                    continue
                raise

        raise last_error or RuntimeError("Deepgram STT retry exhausted")
