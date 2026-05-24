"""Local Whisper STT provider — mlx-whisper (Apple Silicon) or faster-whisper (Linux/CPU)."""

from __future__ import annotations

import asyncio
import platform
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

from hive.stt.base import TranscriptionResult

_HAS_MLX_WHISPER = False
_HAS_FASTER_WHISPER = False
_mlx_whisper_mod: ModuleType | None = None
_faster_whisper_mod: ModuleType | None = None

if sys.platform == "darwin" and platform.machine() == "arm64":
    try:
        import mlx_whisper as _mlx_whisper_mod  # type: ignore[no-redef]

        _HAS_MLX_WHISPER = True
    except ImportError:
        pass

if not _HAS_MLX_WHISPER:
    try:
        import faster_whisper as _faster_whisper_mod  # type: ignore[no-redef]

        _HAS_FASTER_WHISPER = True
    except ImportError:
        pass

_MLX_MODEL_MAP = {
    "tiny": "mlx-community/whisper-tiny",
    "base": "mlx-community/whisper-base",
    "small": "mlx-community/whisper-small",
    "medium": "mlx-community/whisper-medium",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "large-v3": "mlx-community/whisper-large-v3",
}


class WhisperLocal:
    """Local Whisper transcription using mlx-whisper (Apple Silicon) or faster-whisper."""

    def __init__(self, model_size: str = "base") -> None:
        self._model_size = model_size
        self._model: Any = None
        self._backend: str = ""

        if _HAS_MLX_WHISPER:
            self._backend = "mlx"
        elif _HAS_FASTER_WHISPER:
            self._backend = "faster"

    @property
    def available(self) -> bool:
        return self._backend != ""

    def _ensure_model(self) -> None:
        if self._model is not None:
            return

        if self._backend == "mlx":
            repo = _MLX_MODEL_MAP.get(self._model_size, f"mlx-community/whisper-{self._model_size}")
            self._model = repo
        elif self._backend == "faster" and _faster_whisper_mod is not None:
            self._model = _faster_whisper_mod.WhisperModel(
                self._model_size, device="auto", compute_type="default"
            )
        else:
            raise RuntimeError(
                "No whisper backend available. Install one of:\n"
                "  Apple Silicon: pip install mlx-whisper\n"
                "  Linux/CPU:     pip install faster-whisper"
            )

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        self._ensure_model()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._transcribe_sync, audio_path)

    def _transcribe_sync(self, audio_path: Path) -> TranscriptionResult:
        path_str = str(audio_path)

        if self._backend == "mlx" and _mlx_whisper_mod is not None:
            result = _mlx_whisper_mod.transcribe(path_str, path_or_hf_repo=self._model)
            return TranscriptionResult(
                text=result.get("text", "").strip(),
                language=result.get("language", ""),
                provider="mlx-whisper",
            )

        segments, info = self._model.transcribe(path_str)
        text = "".join(s.text for s in segments).strip()
        return TranscriptionResult(
            text=text,
            language=info.language,
            duration_ms=int(info.duration * 1000),
            provider="faster-whisper",
        )

    async def transcribe_bytes(self, audio: bytes, sample_rate: int = 16000) -> TranscriptionResult:
        from hive.stt.recorder import _write_wav

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_path = Path(f.name)

        _write_wav(tmp_path, audio, sample_rate=sample_rate, channels=1)

        try:
            return await self.transcribe(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
