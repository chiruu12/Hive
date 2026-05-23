"""Tests for STT providers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from hive.stt.base import TranscriptionResult
from hive.stt.deepgram_stt import DeepgramSTT
from hive.stt.factory import create_stt_provider
from hive.stt.groq_stt import GroqSTT
from hive.stt.whisper_local import WhisperLocal


class TestTranscriptionResult:
    def test_defaults(self) -> None:
        r = TranscriptionResult(text="hello")
        assert r.text == "hello"
        assert r.language == ""
        assert r.duration_ms == 0
        assert r.provider == ""

    def test_full(self) -> None:
        r = TranscriptionResult(text="hi", language="en", duration_ms=1500, provider="groq")
        assert r.language == "en"
        assert r.duration_ms == 1500

    def test_pydantic_serialization(self) -> None:
        r = TranscriptionResult(text="test", language="en", duration_ms=500, provider="groq")
        d = r.model_dump()
        assert d == {"text": "test", "language": "en", "duration_ms": 500, "provider": "groq"}
        r2 = TranscriptionResult.model_validate(d)
        assert r2.text == "test"

    def test_rejects_negative_duration(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            TranscriptionResult(text="hi", duration_ms=-1)


class TestWhisperLocal:
    def test_available_without_backends(self) -> None:
        with (
            patch("hive.stt.whisper_local._HAS_MLX_WHISPER", False),
            patch("hive.stt.whisper_local._HAS_FASTER_WHISPER", False),
        ):
            w = WhisperLocal()
            w._backend = ""
            assert not w.available

    def test_ensure_model_raises_without_backend(self) -> None:
        w = WhisperLocal()
        w._backend = ""
        with pytest.raises(RuntimeError, match="No whisper backend"):
            w._ensure_model()

    @pytest.mark.asyncio
    async def test_transcribe_mlx(self, tmp_path: Path) -> None:
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake-audio")

        mock_mod = MagicMock()
        mock_mod.transcribe.return_value = {
            "text": " hello world ",
            "language": "en",
            "segments": [],
        }

        w = WhisperLocal(model_size="tiny")
        w._backend = "mlx"
        w._model = "mlx-community/whisper-tiny"

        with patch("hive.stt.whisper_local._mlx_whisper_mod", mock_mod):
            result = await w.transcribe(audio_file)

        assert result.text == "hello world"
        assert result.language == "en"
        assert result.provider == "mlx-whisper"

    @pytest.mark.asyncio
    async def test_transcribe_faster(self, tmp_path: Path) -> None:
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake-audio")

        mock_segment = MagicMock()
        mock_segment.text = " hello world"
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.duration = 2.5

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment], mock_info)

        w = WhisperLocal(model_size="base")
        w._backend = "faster"
        w._model = mock_model

        result = await w.transcribe(audio_file)

        assert result.text == "hello world"
        assert result.language == "en"
        assert result.duration_ms == 2500
        assert result.provider == "faster-whisper"


class TestGroqSTT:
    def test_available_with_key(self) -> None:
        g = GroqSTT(api_key="test-key")
        assert g.available

    def test_not_available_without_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            g = GroqSTT(api_key="")
            assert not g.available

    @pytest.mark.asyncio
    async def test_transcribe(self, tmp_path: Path) -> None:
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake-audio")

        response_data = {"text": " hello ", "language": "en", "duration": 1.5}

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = response_data
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False

        g = GroqSTT(api_key="test-key")
        g._client = mock_client
        result = await g.transcribe(audio_file)

        assert result.text == "hello"
        assert result.language == "en"
        assert result.duration_ms == 1500
        assert result.provider == "groq"

    @pytest.mark.asyncio
    async def test_transcribe_bytes(self) -> None:
        response_data = {"text": "from bytes", "language": "fr", "duration": 0.8}

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = response_data
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False

        g = GroqSTT(api_key="test-key")
        g._client = mock_client
        result = await g.transcribe_bytes(b"raw-audio")

        assert result.text == "from bytes"
        assert result.provider == "groq"


class TestDeepgramSTT:
    def test_available_with_key(self) -> None:
        d = DeepgramSTT(api_key="test-key")
        assert d.available

    def test_not_available_without_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            d = DeepgramSTT(api_key="")
            assert not d.available

    @pytest.mark.asyncio
    async def test_transcribe(self, tmp_path: Path) -> None:
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake-audio")

        response_data = {
            "results": {
                "channels": [
                    {
                        "alternatives": [{"transcript": " hello deepgram "}],
                        "detected_language": "en",
                    }
                ],
                "metadata": {"duration": 2.0},
            }
        }

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = response_data
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False

        d = DeepgramSTT(api_key="test-key")
        d._client = mock_client
        result = await d.transcribe(audio_file)

        assert result.text == "hello deepgram"
        assert result.language == "en"
        assert result.duration_ms == 2000
        assert result.provider == "deepgram"


class TestFactory:
    def test_explicit_groq(self) -> None:
        provider = create_stt_provider("groq")
        assert isinstance(provider, GroqSTT)

    def test_explicit_deepgram(self) -> None:
        provider = create_stt_provider("deepgram")
        assert isinstance(provider, DeepgramSTT)

    def test_explicit_whisper(self) -> None:
        provider = create_stt_provider("whisper")
        assert isinstance(provider, WhisperLocal)

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown STT provider"):
            create_stt_provider("nonexistent")

    def test_auto_detect_groq(self) -> None:
        with (
            patch.object(WhisperLocal, "available", new_callable=lambda: property(lambda s: False)),
            patch.dict("os.environ", {"GROQ_API_KEY": "key123"}),
        ):
            provider = create_stt_provider()
            assert isinstance(provider, GroqSTT)

    def test_auto_detect_deepgram(self) -> None:
        with (
            patch.object(WhisperLocal, "available", new_callable=lambda: property(lambda s: False)),
            patch.dict("os.environ", {"DEEPGRAM_API_KEY": "key456"}, clear=True),
        ):
            provider = create_stt_provider()
            assert isinstance(provider, DeepgramSTT)

    def test_auto_detect_none_raises(self) -> None:
        with (
            patch.object(WhisperLocal, "available", new_callable=lambda: property(lambda s: False)),
            patch.dict("os.environ", {}, clear=True),
        ):
            with pytest.raises(RuntimeError, match="No STT provider available"):
                create_stt_provider()
