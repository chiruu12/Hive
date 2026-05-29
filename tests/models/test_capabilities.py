"""Tests for the provider capability + availability model (A3)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from hive.models.anthropic import Anthropic
from hive.models.base import Availability, BaseProvider, Capability
from hive.models.openai import OpenAI
from hive.models.router import ModelInfo
from hive.runtime.types import GenerateResult, Message


class _DummyProvider(BaseProvider):
    """Minimal provider exercising only the base capability/availability defaults."""

    def __init__(self, available: bool = True) -> None:
        super().__init__("dummy-model")
        self._available = available

    @property
    def available(self) -> bool:
        return self._available

    async def generate_with_metadata(self, *args: Any, **kwargs: Any) -> GenerateResult:
        return GenerateResult(message=Message.assistant("x"), model="dummy-model")

    async def generate_structured(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError


class TestBaseDefaults:
    def test_default_capabilities(self) -> None:
        p = _DummyProvider()
        assert p.supports(Capability.TOOLS)
        assert p.supports(Capability.STRUCTURED_OUTPUT)
        assert not p.supports(Capability.STREAMING)

    def test_availability_derives_from_available(self) -> None:
        assert _DummyProvider(available=True).availability() == Availability.AVAILABLE
        # Base default cannot tell *why* it's down, so it reports UNKNOWN.
        assert _DummyProvider(available=False).availability() == Availability.UNKNOWN


class TestAnthropicAvailability:
    def test_with_key(self) -> None:
        with patch("hive.models.anthropic.get_env", return_value="sk-test"):
            p = Anthropic.lite()
        assert p.available
        assert p.availability() == Availability.AVAILABLE

    def test_without_key_reports_no_api_key(self) -> None:
        with patch("hive.models.anthropic.get_env", return_value=""):
            p = Anthropic.lite()
        assert not p.available
        assert p.availability() == Availability.NO_API_KEY

    def test_capabilities(self) -> None:
        with patch("hive.models.anthropic.get_env", return_value="sk-test"):
            p = Anthropic.lite()
        assert p.supports(Capability.TOOLS)
        assert p.supports(Capability.STRUCTURED_OUTPUT)
        assert p.supports(Capability.STREAMING)


class TestOpenAIAvailability:
    def test_remote_without_key_reports_no_api_key(self) -> None:
        with patch("hive.models.openai.get_env", return_value=""):
            p = OpenAI(api_key=None)
        assert not p.available
        assert p.availability() == Availability.NO_API_KEY

    def test_remote_with_key_available(self) -> None:
        p = OpenAI(api_key="sk-test")
        assert p.available
        assert p.availability() == Availability.AVAILABLE

    def test_local_unreachable(self) -> None:
        p = OpenAI(model="local-model", base_url="http://localhost:1234/v1")
        with patch.object(p, "_check_local_health", return_value=False):
            assert not p.available
            assert p.availability() == Availability.UNREACHABLE

    def test_local_reachable(self) -> None:
        p = OpenAI(model="local-model", base_url="http://localhost:1234/v1")
        with patch.object(p, "_check_local_health", return_value=True):
            assert p.available
            assert p.availability() == Availability.AVAILABLE


class TestModelInfoDetail:
    def test_detail_defaults_to_empty(self) -> None:
        info = ModelInfo("m", "anthropic", True)
        assert info.detail == ""

    def test_detail_carries_reason(self) -> None:
        info = ModelInfo("m", "local", False, "unreachable")
        assert info.detail == "unreachable"
