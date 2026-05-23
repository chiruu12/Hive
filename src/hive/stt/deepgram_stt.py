"""Deepgram Nova-2 STT provider."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from pydantic import BaseModel

from hive.stt.base import TranscriptionResult

_API_URL = "https://api.deepgram.com/v1/listen"
_MODEL = "nova-2"


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

    def __init__(self, api_key: str | None = None, model: str = _MODEL) -> None:
        self._api_key = api_key or os.environ.get("DEEPGRAM_API_KEY", "")
        self._model = model

    @property
    def available(self) -> bool:
        return self._api_key != ""

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        with open(audio_path, "rb") as f:
            audio_data = f.read()
        return await self._transcribe_raw(audio_data)

    async def transcribe_bytes(
        self, audio: bytes, sample_rate: int = 16000
    ) -> TranscriptionResult:
        return await self._transcribe_raw(audio)

    async def _transcribe_raw(self, audio_data: bytes) -> TranscriptionResult:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                _API_URL,
                params={"model": self._model, "detect_language": "true"},
                headers={
                    "Authorization": f"Token {self._api_key}",
                    "Content-Type": "audio/wav",
                },
                content=audio_data,
            )
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
