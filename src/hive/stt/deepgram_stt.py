"""Deepgram Nova-2 STT provider."""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from hive.stt.base import TranscriptionResult

_API_URL = "https://api.deepgram.com/v1/listen"
_MODEL = "nova-2"


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

        data = resp.json()
        result = data.get("results", {})
        channels = result.get("channels", [{}])
        alt = channels[0].get("alternatives", [{}])[0] if channels else {}
        metadata = result.get("metadata", {})

        return TranscriptionResult(
            text=alt.get("transcript", "").strip(),
            language=channels[0].get("detected_language", "") if channels else "",
            duration_ms=int(metadata.get("duration", 0) * 1000),
            provider="deepgram",
        )
