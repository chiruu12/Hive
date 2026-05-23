"""Groq Whisper API STT provider."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import httpx

from hive.stt.base import TranscriptionResult

_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_MODEL = "whisper-large-v3-turbo"


class GroqSTT:
    """Speech-to-text via Groq's hosted Whisper API."""

    def __init__(self, api_key: str | None = None, model: str = _MODEL) -> None:
        self._api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self._model = model

    @property
    def available(self) -> bool:
        return self._api_key != ""

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        async with httpx.AsyncClient(timeout=60) as client:
            with open(audio_path, "rb") as f:
                resp = await client.post(
                    _API_URL,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    files={"file": (audio_path.name, f, "audio/wav")},
                    data={"model": self._model, "response_format": "verbose_json"},
                )
                resp.raise_for_status()

        data = resp.json()
        return TranscriptionResult(
            text=data.get("text", "").strip(),
            language=data.get("language", ""),
            duration_ms=int(data.get("duration", 0) * 1000),
            provider="groq",
        )

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
