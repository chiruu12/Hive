"""Speech-to-text provider protocol and result types."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class TranscriptionResult:
    text: str
    language: str = ""
    duration_ms: int = 0
    provider: str = ""


@runtime_checkable
class STTProvider(Protocol):
    async def transcribe(self, audio_path: Path) -> TranscriptionResult: ...

    async def transcribe_bytes(
        self, audio: bytes, sample_rate: int = 16000
    ) -> TranscriptionResult: ...

    @property
    def available(self) -> bool: ...
