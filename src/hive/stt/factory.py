"""Factory for creating STT providers."""

from __future__ import annotations

from hive.stt.base import STTProvider
from hive.stt.deepgram_stt import DeepgramSTT
from hive.stt.groq_stt import GroqSTT
from hive.stt.whisper_local import WhisperLocal

_PROVIDERS: dict[str, type] = {
    "whisper": WhisperLocal,
    "groq": GroqSTT,
    "deepgram": DeepgramSTT,
}


def create_stt_provider(name: str | None = None) -> STTProvider:
    """Create an STT provider by name, or auto-detect the best available."""
    if name is not None:
        cls = _PROVIDERS.get(name)
        if cls is None:
            raise ValueError(f"Unknown STT provider: {name!r}. Choose from: {list(_PROVIDERS)}")
        return cls()

    # Auto-detect: local whisper first, then cloud APIs
    local = WhisperLocal()
    if local.available:
        return local

    groq = GroqSTT()
    if groq.available:
        return groq

    deepgram = DeepgramSTT()
    if deepgram.available:
        return deepgram

    raise RuntimeError(
        "No STT provider available. Options:\n"
        "  1. Install mlx-whisper (Apple Silicon) or faster-whisper (Linux/CPU)\n"
        "  2. Set GROQ_API_KEY for Groq Whisper API\n"
        "  3. Set DEEPGRAM_API_KEY for Deepgram Nova-2 API"
    )
