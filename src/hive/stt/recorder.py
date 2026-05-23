"""Audio recorder using sounddevice."""

from __future__ import annotations

import logging
import struct
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import sounddevice as sd

    _HAS_SOUNDDEVICE = True
except ImportError:
    sd = None  # type: ignore[assignment,unused-ignore]
    _HAS_SOUNDDEVICE = False


def _write_wav(path: Path, data: bytes, sample_rate: int, channels: int) -> None:
    """Write raw PCM int16 data as a WAV file (no scipy needed)."""
    bits_per_sample = 16
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    data_size = len(data)

    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        fmt = struct.pack(
            "<IHHIIHH",
            16,
            1,
            channels,
            sample_rate,
            byte_rate,
            block_align,
            bits_per_sample,
        )
        f.write(fmt)
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(data)


def _max_input_channels() -> int:
    """Query the default input device for max supported channels."""
    if not _HAS_SOUNDDEVICE:
        return 0
    try:
        info: dict[str, Any] = sd.query_devices(kind="input")  # type: ignore[assignment,unused-ignore]
        return int(info.get("max_input_channels", 1))
    except Exception:
        return 1


class AudioRecorder:
    """Record audio from the default microphone."""

    def __init__(self, sample_rate: int = 16000, channels: int = 1) -> None:
        if not _HAS_SOUNDDEVICE:
            raise ImportError(
                "sounddevice is required for audio recording. "
                "Install it with: pip install hive-agent[audio]"
            )

        max_ch = _max_input_channels()
        if channels > max_ch:
            raise ValueError(
                f"Requested {channels} channels but device supports max {max_ch}. "
                f"Use channels={max_ch} or fewer."
            )

        self._sample_rate = sample_rate
        self._channels = channels
        self._frames: list[bytes] = []
        self._stream: Any = None
        self._lock = threading.Lock()
        self._recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        if self._recording:
            return
        self._frames = []
        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()
        self._recording = True

    def stop(self) -> bytes:
        if not self._recording:
            return b""
        self._stream.stop()
        self._stream.close()
        self._stream = None
        self._recording = False
        with self._lock:
            data = b"".join(self._frames)
            self._frames = []
            return data

    def stop_and_save(self, path: Path | None = None) -> Path:
        audio_bytes = self.stop()
        if path is None:
            import os
            import tempfile

            fd, name = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            path = Path(name)
        _write_wav(path, audio_bytes, self._sample_rate, self._channels)
        return path

    def _callback(self, indata: Any, frames: int, time_info: Any, status: Any) -> None:
        if status:
            logger.warning("Audio callback status: %s", status)
        with self._lock:
            self._frames.append(bytes(indata))
