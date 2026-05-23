"""Speech-to-text providers and audio recording."""

from hive.stt.base import STTProvider, TranscriptionResult
from hive.stt.deepgram_stt import DeepgramSTT
from hive.stt.factory import create_stt_provider
from hive.stt.groq_stt import GroqSTT
from hive.stt.recorder import AudioRecorder
from hive.stt.whisper_local import WhisperLocal

__all__ = [
    "AudioRecorder",
    "STTProvider",
    "TranscriptionResult",
    "WhisperLocal",
    "GroqSTT",
    "DeepgramSTT",
    "create_stt_provider",
]
