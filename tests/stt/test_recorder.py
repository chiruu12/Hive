"""Tests for AudioRecorder."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hive.stt.recorder import AudioRecorder

_SD = "hive.stt.recorder.sd"
_HAS = "hive.stt.recorder._HAS_SOUNDDEVICE"


@pytest.fixture
def mock_sd() -> MagicMock:
    mock = MagicMock()
    mock_stream = MagicMock()
    mock.InputStream.return_value = mock_stream
    return mock


class TestAudioRecorder:
    def test_not_recording_initially(self, mock_sd: MagicMock) -> None:
        with patch(_SD, mock_sd), patch(_HAS, True):
            rec = AudioRecorder()
            assert not rec.is_recording

    def test_start_sets_recording(self, mock_sd: MagicMock) -> None:
        with patch(_SD, mock_sd), patch(_HAS, True):
            rec = AudioRecorder()
            rec.start()
            assert rec.is_recording
            mock_sd.InputStream.assert_called_once()

    def test_start_idempotent(self, mock_sd: MagicMock) -> None:
        with patch(_SD, mock_sd), patch(_HAS, True):
            rec = AudioRecorder()
            rec.start()
            rec.start()
            assert mock_sd.InputStream.call_count == 1

    def test_stop_returns_bytes(self, mock_sd: MagicMock) -> None:
        with patch(_SD, mock_sd), patch(_HAS, True):
            rec = AudioRecorder()
            rec.start()
            rec._frames = [b"\x00\x01", b"\x02\x03"]
            result = rec.stop()
            assert result == b"\x00\x01\x02\x03"
            assert not rec.is_recording

    def test_stop_without_start_returns_empty(self, mock_sd: MagicMock) -> None:
        with patch(_SD, mock_sd), patch(_HAS, True):
            rec = AudioRecorder()
            result = rec.stop()
            assert result == b""

    def test_stop_and_save(self, mock_sd: MagicMock, tmp_path: Path) -> None:
        with patch(_SD, mock_sd), patch(_HAS, True):
            rec = AudioRecorder()
            rec.start()
            rec._frames = [b"\x00\x00" * 100]
            out = tmp_path / "test.wav"
            result = rec.stop_and_save(out)
            assert result == out
            assert out.exists()
            content = out.read_bytes()
            assert content[:4] == b"RIFF"
            assert content[8:12] == b"WAVE"

    def test_stop_and_save_auto_path(self, mock_sd: MagicMock) -> None:
        with patch(_SD, mock_sd), patch(_HAS, True):
            rec = AudioRecorder()
            rec.start()
            rec._frames = [b"\x00\x00" * 10]
            result = rec.stop_and_save()
            assert result.suffix == ".wav"
            assert result.exists()
            result.unlink()

    def test_callback_appends_frames(self, mock_sd: MagicMock) -> None:
        with patch(_SD, mock_sd), patch(_HAS, True):
            rec = AudioRecorder()
            rec._callback(b"\x01\x02\x03\x04", 2, None, None)
            assert rec._frames == [b"\x01\x02\x03\x04"]

    def test_import_error_without_sounddevice(self) -> None:
        with patch(_HAS, False):
            with pytest.raises(ImportError, match="sounddevice"):
                AudioRecorder()
